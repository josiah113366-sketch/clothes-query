from fastapi import Request

from clothes_api.kafka import ClickPublisher
from clothes_api.metrics import Metrics
from clothes_api.store import Store


def store(request: Request) -> Store:
    return request.app.state.store


def publisher(request: Request) -> ClickPublisher:
    return request.app.state.publisher


def metrics(request: Request) -> Metrics:
    return request.app.state.metrics
