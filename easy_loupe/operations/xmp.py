"""Write shared XMP sidecars for photo metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from xml.dom import Node, minidom  # noqa: S408
from xml.parsers.expat import ExpatError

from easy_loupe.operations.common import (
    CreatedFileUndo,
    OperationError,
    OperationSummary,
    UndoPlan,
    backup_existing_file,
    sidecar_path_for_photo,
    undo_operation,
)
from easy_loupe.progress import (
    ProgressReporter,
    ProgressStageDefinition,
    StructuredProgressCallback,
)

if TYPE_CHECKING:
    from pathlib import Path

    from easy_loupe.core.records import PhotoRecord

ProgressCallback = Callable[[str, int], None]
MergePolicy = Literal['preserve', 'replace']

XMP_META_NAMESPACE = 'adobe:ns:meta/'
RDF_NAMESPACE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
XMP_NAMESPACE = 'http://ns.adobe.com/xap/1.0/'
XMPDM_NAMESPACE = 'http://ns.adobe.com/xmp/1.0/DynamicMedia/'
CAP1_NAMESPACE = 'http://www.phaseone.com/cap1/1.0/'
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>'
STANDALONE_DECLARATION = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
)
PRETTY_PRINT_INDENT = '  '


@dataclass(slots=True, frozen=True)
class WriteXmpOptions:
    """Options for writing shared XMP sidecars."""

    merge_policy: MergePolicy


def write_xmp_sidecars(
        current_folder: Path,
        photos: list[PhotoRecord],
        options: WriteXmpOptions,
        progress_callback: ProgressCallback | None = None,
        *,
        progress_snapshot_callback: StructuredProgressCallback | None = None,
) -> OperationSummary:
    """Create or update per-stem XMP sidecars for the provided photos."""
    source_folder = current_folder.expanduser().resolve()
    if not source_folder.is_dir():
        raise FileNotFoundError(f'{source_folder} is not a directory')

    reporter = ProgressReporter(
        'Writing XMP sidecars',
        (
            ProgressStageDefinition('prepare', 'Preparing XMP sidecars'),
            ProgressStageDefinition('write', 'Writing XMP sidecars'),
        ),
        progress_callback=progress_callback,
        snapshot_callback=progress_snapshot_callback,
    )
    reporter.start_stage('prepare', overall_progress=5)

    undo_plan = UndoPlan()
    written_sidecars = 0
    skipped_photos = 0
    total_photos = len(photos)
    try:
        if total_photos == 0:
            # No photos means the XMP loop never advances this stage. Emit a
            # zero-total completion so the structured overlay treats the
            # workflow as a no-op rather than unknown-size completed work.
            reporter.update_stage(
                'write',
                current=0,
                total=0,
                overall_progress=99,
                complete=True,
            )

        for index, photo in enumerate(photos, start=1):
            sidecar_path = sidecar_path_for_photo(source_folder, photo)
            has_any_tags = (
                photo.rating is not None
                or photo.color_label is not None
                or photo.flag is not None
            )
            if not has_any_tags and not sidecar_path.exists():
                skipped_photos += 1
            else:
                _write_photo_sidecar(
                    sidecar_path,
                    photo,
                    options,
                    undo_plan,
                    has_any_tags=has_any_tags,
                )
                written_sidecars += 1

            progress = 5 + int((index / max(total_photos, 1)) * 94)
            reporter.update_stage(
                'write',
                current=index,
                total=total_photos,
                overall_progress=min(progress, 99),
                complete=index == total_photos,
            )
    except Exception:
        undo_operation(undo_plan)
        raise

    reporter.finish('XMP sidecar writing complete', 100)

    return OperationSummary(
        processed_photos=len(photos),
        written_sidecars=written_sidecars,
        skipped_photos=skipped_photos,
        undo_plan=undo_plan,
    )


def _write_photo_sidecar(
        sidecar_path: Path,
        photo: PhotoRecord,
        options: WriteXmpOptions,
        undo_plan: UndoPlan,
        *,
        has_any_tags: bool,
) -> None:
    sidecar_existed = sidecar_path.exists()
    if sidecar_existed:
        backup_existing_file(sidecar_path, undo_plan)

    if options.merge_policy == 'preserve' and sidecar_existed:
        document = _parse_sidecar(sidecar_path)
    else:
        document = _build_empty_sidecar()

    description = _primary_description(document)
    _remove_managed_fields(document)
    _ensure_description_namespaces(description)
    if has_any_tags:
        _append_managed_fields(document, description, photo)

    sidecar_path.write_bytes(_serialize_document(document))
    if sidecar_existed is False:
        undo_plan.entries.append(CreatedFileUndo(sidecar_path))


def _parse_sidecar(sidecar_path: Path) -> minidom.Document:
    try:
        return minidom.parseString(sidecar_path.read_bytes())  # noqa: S318
    except (ExpatError, UnicodeDecodeError) as exc:
        raise OperationError(sidecar_path, 'Malformed XMP sidecar') from exc


def _build_empty_sidecar() -> minidom.Document:
    document = minidom.Document()
    root = document.createElementNS(XMP_META_NAMESPACE, 'x:xmpmeta')
    root.setAttribute('xmlns:x', XMP_META_NAMESPACE)
    root.setAttribute('x:xmptk', 'EasyLoupe')
    document.appendChild(root)

    rdf = document.createElementNS(RDF_NAMESPACE, 'rdf:RDF')
    rdf.setAttribute('xmlns:rdf', RDF_NAMESPACE)
    root.appendChild(rdf)

    description = document.createElementNS(RDF_NAMESPACE, 'rdf:Description')
    description.setAttribute('rdf:about', '')
    _ensure_description_namespaces(description)
    rdf.appendChild(description)
    return document


def _primary_description(document: minidom.Document) -> minidom.Element:
    rdf_nodes = document.getElementsByTagNameNS(RDF_NAMESPACE, 'RDF')
    if rdf_nodes:
        rdf = rdf_nodes[0]
    else:
        root = document.documentElement
        if root is None:
            root = document.createElementNS(XMP_META_NAMESPACE, 'x:xmpmeta')
            root.setAttribute('xmlns:x', XMP_META_NAMESPACE)
            root.setAttribute('x:xmptk', 'EasyLoupe')
            document.appendChild(root)

        rdf = document.createElementNS(RDF_NAMESPACE, 'rdf:RDF')
        rdf.setAttribute('xmlns:rdf', RDF_NAMESPACE)
        root.appendChild(rdf)

    description_nodes = [
        node
        for node in rdf.childNodes
        if node.nodeType == Node.ELEMENT_NODE
        and node.namespaceURI == RDF_NAMESPACE
        and node.localName == 'Description'
    ]
    if description_nodes:
        description = description_nodes[0]
    else:
        description = document.createElementNS(
            RDF_NAMESPACE, 'rdf:Description'
        )
        description.setAttribute('rdf:about', '')
        rdf.appendChild(description)

    assert isinstance(description, minidom.Element)
    if not description.hasAttribute('rdf:about'):
        description.setAttribute('rdf:about', '')

    return description


def _remove_managed_fields(document: minidom.Document) -> None:
    managed_namespaces = {
        (XMP_NAMESPACE, 'Rating'),
        (XMP_NAMESPACE, 'Label'),
        (XMPDM_NAMESPACE, 'good'),
        (XMPDM_NAMESPACE, 'pick'),
        (CAP1_NAMESPACE, 'Flag'),
    }
    for description in document.getElementsByTagNameNS(
        RDF_NAMESPACE, 'Description'
    ):
        for child in list(description.childNodes):
            if child.nodeType != Node.ELEMENT_NODE:
                continue

            if (child.namespaceURI, child.localName) in managed_namespaces:
                description.removeChild(child)

        for namespace, local_name in managed_namespaces:
            if description.hasAttributeNS(namespace, local_name):
                description.removeAttributeNS(namespace, local_name)


def _ensure_description_namespaces(description: minidom.Element) -> None:
    description.setAttribute('xmlns:xmp', XMP_NAMESPACE)
    description.setAttribute('xmlns:xmpDM', XMPDM_NAMESPACE)
    description.setAttribute('xmlns:cap1', CAP1_NAMESPACE)


def _append_managed_fields(
        document: minidom.Document,
        description: minidom.Element,
        photo: PhotoRecord,
) -> None:
    _append_text_element(
        document,
        description,
        XMP_NAMESPACE,
        'xmp:Rating',
        str(photo.rating or 0),
    )
    if photo.color_label is not None:
        _append_text_element(
            document,
            description,
            XMP_NAMESPACE,
            'xmp:Label',
            photo.color_label.title(),
        )

    if photo.flag == 'picked':
        _append_text_element(
            document,
            description,
            XMPDM_NAMESPACE,
            'xmpDM:good',
            'true',
        )
        pick_value = '1'
    elif photo.flag == 'rejected':
        _append_text_element(
            document,
            description,
            XMPDM_NAMESPACE,
            'xmpDM:good',
            'false',
        )
        pick_value = '-1'
    else:
        pick_value = '0'

    _append_text_element(
        document,
        description,
        XMPDM_NAMESPACE,
        'xmpDM:pick',
        pick_value,
    )
    _append_text_element(
        document,
        description,
        CAP1_NAMESPACE,
        'cap1:Flag',
        '1' if photo.flag == 'picked' else '0',
    )


def _append_text_element(
        document: minidom.Document,
        description: minidom.Element,
        namespace: str,
        qualified_name: str,
        value: str,
) -> None:
    element = document.createElementNS(namespace, qualified_name)
    element.appendChild(document.createTextNode(value))
    description.appendChild(element)


def _serialize_document(document: minidom.Document) -> bytes:
    payload = document.toprettyxml(
        indent=PRETTY_PRINT_INDENT,
        encoding='UTF-8',
    )
    payload = _collapse_blank_lines(payload)
    if payload.startswith(XML_DECLARATION):
        return payload.replace(XML_DECLARATION, STANDALONE_DECLARATION, 1)

    return STANDALONE_DECLARATION + b'\n' + payload


def _collapse_blank_lines(payload: bytes) -> bytes:
    lines = payload.splitlines()
    non_blank_lines = [line for line in lines if line.strip()]
    return b'\n'.join(non_blank_lines) + b'\n'
