from typing import Annotated, Generic, Literal, TypeVar
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def image_url(value):
    if value:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("image URL must use HTTP(S) without credentials")
    return value


ImageURL = Annotated[str, Field(max_length=2000), AfterValidator(image_url)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Register(Input):
    account: str = Field(min_length=4, max_length=256)
    password: str = Field(min_length=8, max_length=256)
    confirmation: str


class Login(Input):
    account: str
    password: str


class Profile(Input):
    name: str = Field(default="學習者", min_length=1, max_length=100)
    avatar_url: ImageURL = ""
    bio: str = Field(default="", max_length=2000)
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)
    grade: str = Field(default="", max_length=100)
    experience: str = Field(default="", max_length=200)
    direction: str = Field(default="", max_length=200)


class AdminUser(Register):
    role: Literal["user", "admin", "ban"] = "user"
    name: str = Field(default="學習者", max_length=100)
    avatar_url: ImageURL = ""
    bio: str = Field(default="", max_length=2000)


class AdminUserUpdate(Input):
    role: Literal["user", "admin", "ban"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    avatar_url: ImageURL | None = None
    bio: str | None = Field(default=None, max_length=2000)


class BankInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    picture_url: ImageURL = ""
    version: int | None = None


class QuestionInput(Input):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=100000)
    answer: str = Field(default="", max_length=100000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    review_status: Literal["approved", "pending"] = "approved"
    version: int | None = None


class RelationInput(Input):
    bank_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    question_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class Batch(Input):
    ids: list[str] = Field(min_length=1, max_length=1000)


class InterviewInput(Input):
    position: str = Field(min_length=1, max_length=200)
    experience: str = Field(default="初階", max_length=200)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class EventInput(Input):
    event_id: str = Field(min_length=1, max_length=100)
    event: Literal["start", "chat", "end"]
    message: str = Field(default="", max_length=10000)


class GenerationInput(Input):
    request_id: str = Field(min_length=1, max_length=100)
    direction: str = Field(min_length=1, max_length=200)
    count: int = Field(ge=1, le=20)


class PolicyInput(Input):
    version: int = Field(ge=0)
    value: dict


class UserView(BaseModel):
    id: str
    name: str
    avatar_url: str
    bio: str


class SessionView(UserView):
    role: Literal["user", "admin", "ban"]
    csrf_token: str


class BankView(BaseModel):
    id: str
    title: str
    description: str
    picture_url: str
    creator_id: str
    version: int
    author: UserView | None = None


class QuestionView(BaseModel):
    id: str
    title: str
    content: str
    answer: str
    tags: list[str]
    creator_id: str
    version: int
    review_status: str
    author: UserView | None = None


class MessageView(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class InterviewView(BaseModel):
    id: str
    owner_id: str
    position: str
    experience: str
    difficulty: str
    status: Literal["NOT_STARTED", "ACTIVE", "ENDED"]
    history: list[MessageView]
    version: int
    pending: bool


class JobView(BaseModel):
    id: str
    request_id: str
    state: str
    input: dict
    result: list[str]
    error: str | None
    attempts: int


Item = TypeVar("Item")


class PageView(BaseModel, Generic[Item]):
    items: list[Item]
    page: int
    page_size: int
    total: int


class BankDetailView(BankView):
    question_page: PageView[QuestionView] | None = None


class NavigationView(BaseModel):
    previous_id: str | None
    next_id: str | None
    page: int
