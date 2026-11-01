"""A stand-in for pickle and compile that exhausts the stack, shared by the deep-tree fallback tests (#563)."""


def _raise_recursion_error(*_args: object, **_kwargs: object) -> None:
    raise RecursionError
