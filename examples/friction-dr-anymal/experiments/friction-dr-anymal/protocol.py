"""Every number the experiment depends on, in one place, mirroring prereg §2-§4.

train.py / evaluate.py / aggregate.py import from here and write sha256(protocol.py) into every output,
so an output can be matched to the protocol it ran under. Changing a value after freezing is an erratum,
not an edit.
"""

PREREG_ID = "friction-dr-anymal"
TASK = "Isaac-Velocity-Flat-Anymal-C-v0"

# --- training (prereg §2) ---
TRAIN_SEEDS = (9101, 9102, 9103, 9104, 9105)
SMOKE_SEED = 9100
TRAIN_ITERATIONS = 300
TRAIN_NUM_ENVS = 4096
ARMS = ("control", "treatment")

# Task default of the friction event, as registered. train.py refuses to run if the installed task differs
# (the defaults were read from a local checkout, not from the pinned tag).
DEFAULT_FRICTION_EVENT = {
    "static_friction_range": (0.8, 0.8),
    "dynamic_friction_range": (0.6, 0.6),
    "restitution_range": (0.0, 0.0),
    "num_buckets": 64,
}
TREATMENT_FRICTION = {
    "static_friction_range": (0.25, 1.2),
    "dynamic_friction_range": (0.2, 1.0),
    "make_consistent": True,  # dynamic <= static per material
}
GROUND_FRICTION = 1.0          # static and dynamic, combine mode "multiply"
GROUND_COMBINE_MODE = "multiply"

# --- evaluation (prereg §3-§4) ---
EVAL_SEED = 7
EVAL_NUM_ENVS = 512
EVAL_EPISODES_PER_ENV = 2
EVAL_EPISODE_S = 20.0
DYNAMIC_TO_STATIC = 0.75        # override sets dynamic = 0.75 * static (the task default ratio 0.6 / 0.8)
MAIN_MUS = (0.3, 0.8)
GATE_ICE_MU = 0.05
NOMINAL_MU = 0.8
MAX_MEAN_TRACK_ERR = 0.25       # m/s, episode-mean planar velocity error for success
COMMAND_RANGES = {"lin_vel_x": (-1.0, 1.0), "lin_vel_y": (-1.0, 1.0), "ang_vel_z": (-1.0, 1.0)}
COMMAND_ATOL = 1e-6             # float32 storage of a python float
MATERIAL_ATOL = 1e-6


# --- budget stop rule after the timing smoke (prereg §6) ---
BUDGET_STOP_L4_HOURS = 8.0
SMOKE_ITERATIONS = 50
EVAL_PROCESS_HOURS_EST = 4 / 60     # per evaluation process, start-up included (estimate until measured)
N_EVAL_PROCESSES = 31               # 20 main + 5 ice + 5 default path + 1 zero action
SLACK_HOURS = 0.3


def override_material(mu: float) -> dict:
    return {
        "static_friction_range": (mu, mu),
        "dynamic_friction_range": (DYNAMIC_TO_STATIC * mu, DYNAMIC_TO_STATIC * mu),
    }


def episodes_per_policy() -> int:
    return EVAL_NUM_ENVS * EVAL_EPISODES_PER_ENV
