import core.connection_grid

def test_connection_grid():
    grid = core.connection_grid.ConnectionGrid(8, 8)
    assert grid.get_connection_point_count() == 64
