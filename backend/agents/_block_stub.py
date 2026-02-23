"""
Block stubs for cross-reference scanning.
Lightweight dataclasses avoiding DB dependency at reference scan time.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass


@dataclass
class BlockStub:
    block_id: str
    text_content: str
    page_id: str


def make_block_stubs(pages_classified: list, document_id: str) -> list[BlockStub]:
    stubs = []
    order = 0
    for page_number, classified_list in pages_classified:
        for cb in classified_list:
            if not cb.raw.text:
                order += 1
                continue
            bid_raw = f"{document_id}:p{page_number}:b{order:04d}"
            bid = hashlib.sha1(bid_raw.encode()).hexdigest()[:16]
            page_id = f"{document_id}:p{page_number}"
            stubs.append(BlockStub(
                block_id=bid,
                text_content=cb.raw.text,
                page_id=page_id,
            ))
            order += 1
    return stubs
