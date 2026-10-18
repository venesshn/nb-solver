"""Enumerations shared by the domain model and the effect parser."""

from enum import StrEnum


class Element(StrEnum):
    HEART = "Heart"
    SKILL = "Skill"
    BODY = "Body"
    BRAVERY = "Bravery"
    WISDOM = "Wisdom"


class AttackRange(StrEnum):
    SHORT = "Short"
    MID = "Mid"
    LONG = "Long"
    VAST = "Vast"


class JutsuShape(StrEnum):
    CIRCLE = "Circle"
    CONE = "Cone"
    LINE = "Line"
    RECTANGLE = "Rectangle"
    SELF = "Self"
