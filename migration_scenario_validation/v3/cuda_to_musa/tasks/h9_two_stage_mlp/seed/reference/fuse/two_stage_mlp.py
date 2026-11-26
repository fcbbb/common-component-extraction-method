import torch
import torch.nn as nn


class Model(nn.Module):
    """Two affine -> exact GELU -> feature-softmax stages."""

    def __init__(self, in_features, hidden, out_features):
        super().__init__()
        self.linear1 = nn.Linear(in_features, hidden)
        self.linear2 = nn.Linear(hidden, out_features)

    def forward(self, x):
        x = self.linear1(x)
        x = torch.nn.functional.gelu(x)
        x = torch.nn.functional.softmax(x, dim=1)
        x = self.linear2(x)
        x = torch.nn.functional.gelu(x)
        x = torch.nn.functional.softmax(x, dim=1)
        return x


def get_inputs():
    return [torch.rand(37, 64)]


def get_init_inputs():
    return [64, 16, 2]
