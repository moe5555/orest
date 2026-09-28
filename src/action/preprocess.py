"""MMAction2's skeleton test pipeline, reproduced in numpy.

The exported network is only the network (src/scripts/export_ntu_stgcn.py);
everything the model's config does to a pose sequence before it arrives has to
happen here, in the same order and the same number formats, or the model is
fed something it was never trained on. The config's test pipeline is

    PreNormalize2D
    GenSkeFeat(dataset='coco', feats=['j'])
    UniformSampleFrames(clip_len=100, num_clips=10, test_mode=True)
    PoseDecode
    FormatGCNInput(num_person=2)

and each function below is one or two of those steps. The result agrees bit
for bit with MMAction2's own on the reference sequence
(tests/fixtures/ntu120_reference.npz).
"""

import numpy as np

CLIP_LEN = 100
NUM_CLIPS = 10
NUM_PERSON = 2

# UniformSampleFrames reseeds NumPy's global generator with this before
# sampling test clips. A local legacy generator seeded alike draws the same
# numbers without touching the global state.
SEED = 255


def normalise(keypoints: np.ndarray, img_shape: tuple[int, int]) -> np.ndarray:
    """PreNormalize2D: coordinates to -1..1 about the image centre.

    Computed in float16, as MMAction2 does: its skeleton inference stores the
    keypoints as float16 before the pipeline runs. A missing person, all
    zeros, becomes -1 -1 here, as in training.
    """
    height, width = img_shape
    normalised = keypoints.astype(np.float16)
    normalised[..., 0] = (normalised[..., 0] - (width / 2)) / (width / 2)
    normalised[..., 1] = (normalised[..., 1] - (height / 2)) / (height / 2)
    return normalised


def sample_indices(num_frames: int, clip_len: int = CLIP_LEN,
                   num_clips: int = NUM_CLIPS, seed: int = SEED) -> np.ndarray:
    """UniformSampleFrames in test mode: frame indices for every clip, concatenated.

    Shorter sequences are looped to fill a clip; up to twice as long, frames
    are spread by randomly inserted skips; longer still, one frame is drawn
    from each of clip_len equal segments. The draws come from a generator
    reseeded on every call, so the same length always samples alike.

    MMAction2 also marks frames where the number of people changes and would
    round their indices down; every index drawn here is already an integer, so
    that step never changes anything and is left out.
    """
    random = np.random.RandomState(seed)
    clips = []
    for clip in range(num_clips):
        if num_frames < clip_len:
            start = clip if num_frames < num_clips else clip * num_frames // num_clips
            indices = np.arange(start, start + clip_len)
        elif num_frames < 2 * clip_len:
            basic = np.arange(clip_len)
            skips = random.choice(clip_len + 1, num_frames - clip_len, replace=False)
            offset = np.zeros(clip_len + 1, dtype=np.int64)
            offset[skips] = 1
            indices = basic + np.cumsum(offset)[:-1]
        else:
            bounds = np.array([i * num_frames // clip_len for i in range(clip_len + 1)])
            indices = bounds[:clip_len] + random.randint(np.diff(bounds))
        clips.append(indices)
    return np.mod(np.concatenate(clips), num_frames)


def clips(keypoints: np.ndarray, scores: np.ndarray,
          img_shape: tuple[int, int]) -> np.ndarray:
    """A pose sequence as the network takes it.

    keypoints: (people, frames, 17, 2) in pixels; scores: (people, frames, 17).
    A person absent from a frame is zeros there. Returns
    (NUM_CLIPS, NUM_PERSON, CLIP_LEN, 17, 3) float32: x, y and score per joint,
    extra people dropped and missing ones padded with zeros.
    """
    joints = np.concatenate([normalise(keypoints, img_shape),
                             scores.astype(np.float16)[..., None]], axis=-1)

    num_frames = joints.shape[1]
    joints = joints[:, sample_indices(num_frames)].astype(np.float32)

    people = joints.shape[0]
    if people < NUM_PERSON:
        padding = np.zeros((NUM_PERSON - people,) + joints.shape[1:], dtype=joints.dtype)
        joints = np.concatenate([joints, padding], axis=0)
    joints = joints[:NUM_PERSON]

    _, frames, points, channels = joints.shape
    return np.ascontiguousarray(
        joints.reshape(NUM_PERSON, NUM_CLIPS, frames // NUM_CLIPS, points, channels)
        .transpose(1, 0, 2, 3, 4))
