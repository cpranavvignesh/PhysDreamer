import torch
import torch.nn.functional as F
from jaxtyping import Float, Int, Shaped
from torch import Tensor, nn
from typing import Literal, Optional, Sequence, Tuple, List
from motionrep.field_components.encoding import (
    TemporalKplanesEncoding,
    TriplanesEncoding,
)
from motionrep.field_components.mlp import MLP
from motionrep.operators.rotation import rotation_6d_to_matrix, quaternion_to_matrix
from motionrep.data.scene_box import SceneBox


class TemporalKplanesOffsetfields(nn.Module):
    """Temporal Offsets fields.

    Args:
        aabb: axis-aligned bounding box.
            aabb[0] is the minimum (x,y,z) point.
            aabb[1] is the maximum (x,y,z) point.
        resolutions: resolutions of the kplanes. in an order of [x, y, z ,t].

    """

    def __init__(
        self,
        aabb: Float[Tensor, "2 3"],
        resolutions: Sequence[int],
        feat_dim: int = 64,
        init_a: float = 0.1,
        init_b: float = 0.5,
        reduce: Literal["sum", "product", "cat"] = "sum",
        num_decoder_layers=2,
        decoder_hidden_size=64,
        add_spatial_triplane: bool = True,
        zero_init: bool = True,
    ):
        super().__init__()

        self.register_buffer("aabb", aabb)
        self.output_dim = 3

        self.temporal_kplanes_encoding = TemporalKplanesEncoding(
            resolutions, feat_dim, init_a, init_b, reduce
        )

        self.add_spatial_triplane = add_spatial_triplane
        if add_spatial_triplane:
            self.spatial_kplanes_encoding = TriplanesEncoding(
                resolutions[:-1], feat_dim, init_a, init_b, reduce
            )
            feat_dim = feat_dim * 2

        self.decoder = MLP(
            feat_dim,
            num_decoder_layers,
            layer_width=decoder_hidden_size,
            out_dim=self.output_dim,
            skip_connections=None,
            activation=nn.ReLU(),
            out_activation=None,
            zero_init=zero_init,
        )

    def forward(
        self, inp: Float[Tensor, "*bs 4"]
    ) -> Tuple[Float[Tensor, "*bs 3 3"], Float[Tensor, "*bs 3"]]:
        inpx, inpt = inp[:, :3], inp[:, 3:]

        # shift to [-1, 1]
        inpx = SceneBox.get_normalized_positions(inpx, self.aabb) * 2.0 - 1.0

        inpt = inpt * 2.0 - 1.0

        inp = torch.cat([inpx, inpt], dim=-1)
        output = self.temporal_kplanes_encoding(inp)

        if self.add_spatial_triplane:
            spatial_output = self.spatial_kplanes_encoding(inpx)
            output = torch.cat([output, spatial_output], dim=-1)

        output = self.decoder(output)

        return output

    def compute_smoothess_loss(
        self,
    ):
        smothness_loss = self.temporal_kplanes_encoding.compute_plane_tv()
        temporal_smoothness_loss = (
            self.temporal_kplanes_encoding.compute_temporal_smoothness()
        )

        if self.add_spatial_triplane:
            smothness_loss += self.spatial_kplanes_encoding.compute_plane_tv()

        return smothness_loss + temporal_smoothness_loss

    def compute_loss(
        self,
        inp: Float[Tensor, "*bs 4"],
        trajectory: Float[Tensor, "*bs 3"],
        loss_func,
    ):
        inpx, inpt = inp[:, :3], inp[:, 3:]

        output = self(inp)

        rec_traj = inpx + output

        rec_loss = loss_func(rec_traj, trajectory)

        return rec_loss

    def arap_loss(self, inp):
        pass

    def forward_with_plane_coefs(
        self,
        plane_coefs: List[Float[Tensor, "feat_dim H W"]],
        inp: Float[Tensor, "*bs 4"],
    ):
        """
        Args:
            pass
        """

        inpx, inpt = inp[:, :3], inp[:, 3:]

        # shift to [-1, 1]
        inpx = SceneBox.get_normalized_positions(inpx, self.aabb) * 2.0 - 1.0

        inpt = inpt * 2.0 - 1.0

        inp = torch.cat([inpx, inpt], dim=-1)
        output = self.temporal_kplanes_encoding.functional_forward(
            plane_coefs, inp, reduce=self.temporal_kplanes_encoding.reduce
        )

        if self.add_spatial_triplane:
            spatial_output = self.spatial_kplanes_encoding(inpx)
            output = torch.cat([output, spatial_output], dim=-1)

        output = self.decoder(output)

        return output
