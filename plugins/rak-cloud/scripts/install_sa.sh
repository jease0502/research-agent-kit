#!/usr/bin/env bash
# Create the service account rak VMs run as: it may delete VMs whose name starts with the configured prefix and
# read/write the configured bucket, nothing else. Then check that the permissions really apply.
#
#   bash install_sa.sh .rak/cloud.json             # DRY RUN (default): print every gcloud command, change nothing
#   bash install_sa.sh .rak/cloud.json --apply     # run them (an IAM change: the project owner decides)
#   bash install_sa.sh .rak/cloud.json --verify    # read-only: SA exists, bindings present
#   bash install_sa.sh .rak/cloud.json --canary    # DRY RUN of a ~US$0.01 e2-micro that tests the permissions as the SA
#   bash install_sa.sh .rak/cloud.json --canary --apply
#
# Why: the default compute service account often has no compute permissions at all. A VM's idle guard then cannot
# delete itself, falls back to shutdown, and the disk keeps billing - and from outside a stopped VM looks handled.
#
# Not verified against a live project yet: the IAM condition on the instance name below. The canary is how you find out:
# it runs, as this SA, the same permission test vm_job.sh runs at start (testIamPermissions on itself + on the bucket).
set -euo pipefail
CFG=${1:?usage: install_sa.sh <cloud.json> [--apply|--verify|--canary [--apply]]}; shift
MODE=install; APPLY=0
for a in "$@"; do case $a in --apply) APPLY=1;; --verify) MODE=verify;; --canary) MODE=canary;; *) echo "unknown flag $a"; exit 2;; esac; done
py() { python3 -c "import json,sys; c=json.load(open(sys.argv[1])); print($1)" "$CFG" 2>/dev/null || python -c "import json,sys; c=json.load(open(sys.argv[1])); print($1)" "$CFG"; }
ACCOUNT=$(py 'c["account"]'); PROJECT=$(py 'c["project"]'); SA=$(py 'c["service_account"]')
BUCKET_URL=$(py 'c["bucket"]'); PREFIX=$(py 'c["name_prefix"]'); ZONE=$(py 'c["zones"][0]')
BUCKET=gs://$(echo "${BUCKET_URL#gs://}" | cut -d/ -f1)
SA_NAME=${SA%%@*}; ROLE_ID=rakSelfDelete
for v in "$ACCOUNT" "$PROJECT" "$SA" "$BUCKET" "$PREFIX"; do [[ "$v" == *"<"* || -z "$v" ]] && { echo "cloud.json still has placeholders"; exit 2; }; done
[[ "$SA" == *"@$PROJECT.iam.gserviceaccount.com" ]] || { echo "service_account must be <name>@$PROJECT.iam.gserviceaccount.com"; exit 2; }
export CLOUDSDK_CORE_ACCOUNT=$ACCOUNT CLOUDSDK_CORE_PROJECT=$PROJECT
G=${RAK_GCLOUD_BIN:-gcloud}

run() {  # print always; execute only with --apply
  printf '%q ' "$G" "$@"; echo
  (( APPLY )) || return 0
  timeout 300 "$G" "$@"
}

COND="expression=resource.name.extract('instances/{name}').startsWith('$PREFIX'),title=rak-only-$PREFIX,description=delete only VMs named $PREFIX*"

case $MODE in
install)
  (( APPLY )) || echo "# DRY RUN - nothing is changed. Re-run with --apply to execute (an IAM change: the project owner decides)."
  run iam service-accounts create "$SA_NAME" --display-name="rak job runner"
  run iam roles create "$ROLE_ID" --project="$PROJECT" --title="rak self-delete" \
      --permissions=compute.instances.get,compute.instances.delete,compute.zoneOperations.get --stage=GA
  run projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
      --role="projects/$PROJECT/roles/$ROLE_ID" --condition="$COND"
  run storage buckets add-iam-policy-binding "$BUCKET" --member="serviceAccount:$SA" --role=roles/storage.objectAdmin
  # the person creating VMs must be allowed to attach this SA to them
  run iam service-accounts add-iam-policy-binding "$SA" --member="user:$ACCOUNT" --role=roles/iam.serviceAccountUser
  (( APPLY )) && echo "# applied. Now run: bash install_sa.sh $CFG --verify  and  --canary --apply"
  ;;
verify)
  fail=0
  ok() { echo "OK   $*"; }; bad() { echo "FAIL $*"; fail=1; }
  timeout 120 "$G" iam service-accounts describe "$SA" --format="value(email)" >/dev/null 2>&1 && ok "service account exists" || bad "service account $SA not found"
  pol=$(timeout 120 "$G" projects get-iam-policy "$PROJECT" --format=json 2>/dev/null || true)
  grep -q "roles/$ROLE_ID" <<<"$pol" && grep -q "serviceAccount:$SA" <<<"$pol" && ok "project binding for $ROLE_ID" || bad "no project binding of $ROLE_ID to $SA"
  bpol=$(timeout 120 "$G" storage buckets get-iam-policy "$BUCKET" --format=json 2>/dev/null || true)
  grep -q "serviceAccount:$SA" <<<"$bpol" && ok "bucket binding on $BUCKET" || bad "no bucket binding on $BUCKET"
  echo "# static check only. Bindings that look right can still not apply (conditions, propagation): run --canary."
  exit $fail
  ;;
canary)
  NAME="${PREFIX}sa-canary-$(date +%s)"
  OUTURL="${BUCKET_URL%/}/_canary/$NAME"
  HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  T=$(mktemp); trap 'rm -f "$T"' EXIT
  { echo '#!/usr/bin/env bash'
    echo "RAK_OUT_URL=$OUTURL/out"
    sed -n '/^selfcheck_permissions() {/,/^}/p' "$HERE/../../../templates/cloud/vm_job.sh"
    echo 'r=$(selfcheck_permissions); echo "$r" | gcloud storage cp - "$RAK_OUT_URL/selfcheck.txt"'
    echo 'M=http://metadata.google.internal/computeMetadata/v1/instance; n=$(curl -sf -H "Metadata-Flavor: Google" $M/name); z=$(curl -sf -H "Metadata-Flavor: Google" $M/zone)'
    echo 'gcloud compute instances delete "$n" --zone="${z##*/}" --quiet || shutdown -h now'
  } > "$T"
  bash -n "$T"
  (( APPLY )) || echo "# DRY RUN - the canary is not created. --canary --apply creates it (e2-micro, max-run 15m, deletes itself)."
  run compute instances create "$NAME" --zone="$ZONE" --machine-type=e2-micro --provisioning-model=STANDARD \
      --instance-termination-action=DELETE --max-run-duration=15m --boot-disk-auto-delete \
      --image-family=debian-12 --image-project=debian-cloud --service-account="$SA" \
      --scopes=https://www.googleapis.com/auth/cloud-platform --metadata-from-file=startup-script="$T" \
      --labels=owner=rak-sa-canary
  if (( APPLY )); then
    echo "# waiting up to 10 min for $OUTURL/out/selfcheck.txt and for the canary to delete itself"
    for i in $(seq 40); do
      r=$(timeout 60 "$G" storage cat "$OUTURL/out/selfcheck.txt" 2>/dev/null || true)
      [ -n "$r" ] && break; sleep 15
    done
    echo "$r"
    st=$(timeout 60 "$G" compute instances describe "$NAME" --zone="$ZONE" --format="value(status)" 2>&1 || true)
    grep -q "^DELETE_OK$" <<<"$r" && grep -q "^WRITE_OK$" <<<"$r" && echo "CANARY permissions OK" || echo "CANARY permissions MISSING"
    grep -qiE "was not found|notFound" <<<"$st" && echo "CANARY deleted itself" || echo "CANARY did not delete itself (state: $st) - delete it by hand: gcloud compute instances delete $NAME --zone=$ZONE"
  fi
  ;;
esac
