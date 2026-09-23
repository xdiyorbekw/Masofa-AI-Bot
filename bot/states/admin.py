from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_username = State()
    waiting_password = State()
    authenticated = State()
    waiting_broadcast_content = State()
    waiting_broadcast_confirmation = State()
