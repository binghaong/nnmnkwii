from __future__ import with_statement, print_function, absolute_import

from nnmnkwii.functions.mlpg import build_win_mats
from nnmnkwii.functions.mlpg import mlpg_numpy

from torch.autograd import Function
import torch
import numpy as np
import bandmat as bm


# Note: this is written against pytorch 0.1.12. This is not compatible with
# pytorch master.
class MLPG(Function):
    """MLPG as autograd function

    f : (T, D) -> (T, static_dim)
    """

    def __init__(self, static_dim, variance_frames, windows):
        super(MLPG, self).__init__()
        self.static_dim = static_dim
        self.windows = windows
        self.variance_frames = variance_frames

    def forward(self, mean_frames):
        assert mean_frames.dim() == 2  # we cannot do MLPG on minibatch
        variance_frames = self.variance_frames
        self.save_for_backward(mean_frames)

        T, D = mean_frames.size()
        assert mean_frames.size() == variance_frames.size()
        assert self.static_dim == D // len(self.windows)

        mean_frames_np = mean_frames.numpy()
        variance_frames_np = variance_frames.numpy()
        y = mlpg_numpy(mean_frames_np, variance_frames_np, self.windows)
        y = torch.from_numpy(y.astype(np.float32))
        return y

    def backward(self, grad_output):
        mean_frames, = self.saved_tensors
        variance_frames = self.variance_frames

        T, D = mean_frames.size()
        win_mats = build_win_mats(self.windows, T)

        grads = torch.zeros(T, D)
        for d in range(self.static_dim):
            for win_idx, win_mat in enumerate(win_mats):
                # cast to float64 for bandmat
                precisions = 1 / \
                    variance_frames[:, win_idx * self.static_dim +
                                    d].numpy().astype(np.float64)

                # R: W^{t}PW where `t` means transpose
                sdw = win_mat.l + win_mat.u
                R = bm.zeros(sdw, sdw, T)  # overwritten in the next line
                bm.dot_mm_plus_equals(win_mat.T, win_mat,
                                      target_bm=R, diag=precisions)
                # r: W^{t}P
                r = bm.dot_mm(win_mat.T, bm.diag(precisions))

                # grad = R^{-1}r
                grad = np.linalg.solve(R.full(), r.full())
                assert grad.shape == (T, T)

                # Finally we get grad for a particular dimention
                grads[:, win_idx * self.static_dim + d] = torch.from_numpy(
                    grad_output[:, d].numpy().T.dot(grad).flatten())

        return grads


def mlpg(mean_frames, variance_frames, windows):
    T, D = mean_frames.size()
    assert mean_frames.size() == variance_frames.size()
    static_dim = D // len(windows)
    return MLPG(static_dim, variance_frames, windows)(mean_frames)
