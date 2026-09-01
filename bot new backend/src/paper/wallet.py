from dataclasses import dataclass


@dataclass
class PaperWallet:
    balance: float = 1000.0

    def can_spend(self, amount: float) -> bool:
        return self.balance >= amount

    def debit(self, amount: float):
        if amount > self.balance:
            raise ValueError("Insufficient paper balance")
        self.balance -= amount

    def credit(self, amount: float):
        self.balance += amount
