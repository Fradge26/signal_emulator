from pyproj import Transformer


class CoordinateTransformer:
    def __init__(self, source_epsg_code, target_epsg_code):
        self.transformer = Transformer.from_crs(f"epsg:{source_epsg_code}", f"epsg:{target_epsg_code}", always_xy=True)

    def transform(self, x, y):
        return self.transformer.transform(x, y)
