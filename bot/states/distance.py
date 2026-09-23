from aiogram.fsm.state import State, StatesGroup


class DistanceStates(StatesGroup):
    waiting_start = State()
    waiting_destination = State()
