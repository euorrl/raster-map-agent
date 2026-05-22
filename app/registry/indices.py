from pydantic import BaseModel


class IndexConfig(BaseModel):
    name: str
    required_bands: list[str]
    index_formula: str


INDEX_REGISTRY = {
    "NDVI": IndexConfig(
        name="NDVI",
        required_bands=["B04", "B08"],
        index_formula="(nir - red) / (nir + red)",
    )
}


def get_index_config(index_name: str) -> IndexConfig:
    normalized_index_name = index_name.upper()

    try:
        return INDEX_REGISTRY[normalized_index_name]
    except KeyError as error:
        raise ValueError(f"Unsupported index: {index_name}") from error
