from dataclasses import dataclass


@dataclass(slots=True)
class ResolverUserError(Exception):
    reason_code: str
    message: str
    repo: str
    resolver_kind: str

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class BuildUserError(Exception):
    reason_code: str
    message: str
    image_name: str
    target_name: str

    def __str__(self) -> str:
        return self.message
