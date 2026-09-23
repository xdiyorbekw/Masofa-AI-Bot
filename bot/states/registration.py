from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_language = State()
    waiting_full_name = State()
