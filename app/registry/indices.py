from pydantic import BaseModel


class IndexConfig(BaseModel):
    """栅格指数配置。

    Attributes:
        name: 标准指数名称，例如 ``NDVI``。
        required_bands: 计算该指数需要的源波段。
        index_formula: 便于文档和元数据展示的人类可读公式。
    """

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
    """返回已支持栅格指数的配置。

    Args:
        index_name: 请求的指数名称，匹配时不区分大小写。

    Returns:
        匹配到的指数配置。

    Raises:
        ValueError: 当请求的指数尚未注册时抛出。
    """

    normalized_index_name = index_name.upper()

    try:
        return INDEX_REGISTRY[normalized_index_name]
    except KeyError as error:
        raise ValueError(f"Unsupported index: {index_name}") from error
