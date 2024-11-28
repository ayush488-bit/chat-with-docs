from typing import Callable, Iterable, TypeVar, Union

IterableItemType = TypeVar('IterableItemType')

def find(pred: Callable[[IterableItemType], bool], iterable: Iterable[IterableItemType]) -> Union[IterableItemType, None]:
    for element in iterable:
        if pred(element):
            return element
    return None
