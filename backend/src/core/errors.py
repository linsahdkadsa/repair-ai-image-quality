from __future__ import annotations


class AppError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.cause = cause


ERRORS: dict[str, tuple[int, str]] = {
    "AUTH_REQUIRED": (401, "需要认证"),
    "AUTH_INVALID": (401, "凭据无效"),
    "AUTH_RESTART_REQUIRED": (409, "环境变量凭据需要受控重启后生效"),
    "ROLE_FORBIDDEN": (403, "权限不足"),
    "ORIGIN_FORBIDDEN": (403, "请求来源不受信任"),
    "UPLOAD_NOT_FOUND": (404, "上传不存在"),
    "UPLOAD_EMPTY": (400, "上传文件为空"),
    "UPLOAD_TOO_LARGE": (413, "上传文件超过大小限制"),
    "IMAGE_PIXELS_EXCEEDED": (413, "图像像素超过限制"),
    "IMAGE_DECODE_FAILED": (400, "图像无法解码"),
    "IMAGE_TYPE_MISMATCH": (415, "图像类型与扩展名或媒体类型不一致"),
    "UPLOAD_EXPIRED": (409, "上传已过期"),
    "UPLOAD_ALREADY_REFERENCED": (409, "上传已被引用"),
    "STORAGE_FULL": (507, "存储空间不足"),
    "DATA_ROOT_LOCKED": (503, "数据目录已被其他实例占用"),
    "NOT_FOUND": (404, "资源不存在"),
    "VALIDATION_ERROR": (422, "请求字段无效"),
    "INTERNAL_ERROR": (500, "服务器内部错误"),
}


def app_error(error_code: str, *, cause: Exception | None = None) -> AppError:
    status_code, message = ERRORS[error_code]
    return AppError(error_code, message, status_code, cause=cause)
