from client import Twitch
from oauth import ClientCredentials
from collections import Counter


def test_double_whitespace_in_func_docstring(cls):
    # NOTE: dir function is sorted and thus attributes in class
    # may not appear in the order in which they were implemented

    for attr in dir(cls):
        if not attr.endswith("__") and callable(getattr(cls, attr)):
            func = getattr(cls, attr)
            func_docstring = func.__doc__
            if not func_docstring:
                continue
            else:
                docstring_split = func_docstring.split("\n")
                if len(docstring_split) == 1:
                    if (
                        not docstring_split[0] == ""
                        and not docstring_split[0].isspace()
                    ):
                        double_whitespace_check(cls, func, docstring_split[0])
                else:
                    for lineno, line in enumerate(docstring_split):
                        if not line == "" and not line.isspace():
                            double_whitespace_check(cls, func, line, lineno)
    print("\u533A" * 40)
    print(f"No double whitespace found in {cls.__name__} class docstrings")


def double_whitespace_check(cls, func, line, lineno=1):
    word_counter = Counter(line.split())

    # len method for Counter i.e. len(Counter(line.split())
    # does not take into account the occurence of the same word
    # but this procedure does
    len_counter = sum(word_counter.values())
    len_word_split = len(line.strip().split(" "))
    whitespace_msg = (
        f"{cls.__name__}.{func.__name__} doctring lineno {lineno} has "
        f"double whitespace.\nLine in reference here: {line.strip()}"
    )
    assert len_counter == len_word_split, whitespace_msg


if __name__ == "__main__":
    test_double_whitespace_in_func_docstring(Twitch)
    test_double_whitespace_in_func_docstring(ClientCredentials)
