from __future__ import annotations

from navigation_terrain_hydrology import _best_supported_downstream
from navigation_terrain_morphometry import _connect_supported_branch_gaps


class _IterationCountingGrid(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.iteration_count = 0

    def __iter__(self):
        self.iteration_count += 1
        return super().__iter__()


class _ItemsForbiddenIndex(dict):
    def items(self):
        raise AssertionError("downstream lookup must not rebuild the inverse index")


def test_branch_gap_search_scans_dem_origin_once_not_once_per_proposal() -> None:
    resolution_m = 20
    elevations = _IterationCountingGrid(
        {
            (x * resolution_m, y * resolution_m): 1000 + x
            for x in range(20)
            for y in range(20)
        }
    )
    candidates = {
        (0.0, 100.0): {
            "point": (0.0, 100.0),
            "tangent": (1.0, 0.0),
            "score": 8.0,
        },
        (20.0, 100.0): {
            "point": (20.0, 100.0),
            "tangent": (1.0, 0.0),
            "score": 8.0,
        },
        (100.0, 100.0): {
            "point": (100.0, 100.0),
            "tangent": (0.0, 1.0),
            "score": 10.0,
        },
        (100.0, 120.0): {
            "point": (100.0, 120.0),
            "tangent": (0.0, 1.0),
            "score": 10.0,
        },
    }
    graph = {
        (0.0, 100.0): {(20.0, 100.0)},
        (20.0, 100.0): {(0.0, 100.0)},
        (100.0, 100.0): {(100.0, 120.0)},
        (100.0, 120.0): {(100.0, 100.0)},
    }

    _connect_supported_branch_gaps(
        graph,
        candidates,
        elevations,
        resolution_m=resolution_m,
        maximum_bridge_cells=5.25,
    )

    assert elevations.iteration_count == 2
    assert (100.0, 100.0) in graph[(20.0, 100.0)]


def test_downstream_lookup_uses_precomputed_cell_index() -> None:
    cell = (0.0, 0.0)
    target = (20.0, 0.0)
    supported = {
        cell: {
            "point": cell,
            "flow_vector": (1.0, 0.0),
            "flow_accumulation": 2.0,
            "conditioned_elevation_m": 1000.0,
        },
        target: {
            "point": target,
            "flow_vector": (1.0, 0.0),
            "flow_accumulation": 3.0,
            "conditioned_elevation_m": 990.0,
        },
    }
    index_by_cell = _ItemsForbiddenIndex({cell: (0, 0), target: (0, 1)})

    result = _best_supported_downstream(
        cell,
        (0, 0),
        supported[cell],
        supported,
        index_by_cell,
        {(0, 0): cell, (0, 1): target},
        {(0, 0): [(0, 1, 1.0)]},
        resolution_m=20,
    )

    assert result == target
