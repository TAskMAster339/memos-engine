class User:
    name: str
    age: int

    def get_name(self) -> str:
        return self.name


class Printer:
    def print(self, msg: str) -> None:
        pass
