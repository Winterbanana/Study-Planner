from dataclasses import dataclass

@dataclass
class Task:
    course: str
    activity: str
    deadline: str
    status: str
    student_id: int

@dataclass
class User:
    email: str
    password: str