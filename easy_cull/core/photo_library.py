"""Photo-library service over the internal core implementation modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import easy_cull.analysis.scenes as _analysis_scenes_module
import easy_cull.core.exif as _exif_module
import easy_cull.core.preview as _preview_module
from easy_cull.core.folder_loading import (
    load_folder_state as _load_folder_state,
)
from easy_cull.core.metadata import (
    normalize_scene_groups as _normalize_scene_groups,
)
from easy_cull.core.metadata import (
    serialize_metadata_entries as _serialize_metadata_entries,
)
from easy_cull.core.metadata import (
    validate_and_apply_metadata as _validate_and_apply_metadata,
)
from easy_cull.core.metadata import (
    write_folder_metadata as _write_folder_metadata,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from easy_cull.core.records import (
        PhotoRecord,
        SceneGroup,
    )

MIN_SCENE_MERGE_PHOTO_COUNT = 2


class PhotoLibrary:
    """
    Photo-library service for folder loading, metadata, previews, and scenes.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = _preview_module.make_cache_dir(cache_dir)
        self.current_folder: Path | None = None
        self.folder_label: str | None = None
        self.photos: list[PhotoRecord] = []
        self._photo_map: dict[str, PhotoRecord] = {}
        self.scenes: list[SceneGroup] = []
        self.scene_source: str | None = None
        self.scene_detection_done = False

    def load_folder(
            self,
            folder: Path,
            *,
            metadata_entries: dict[str, Any] | None = None,
            folder_label: str | None = None,
            progress_callback: Callable[[str, int], None] | None = None,
    ) -> None:
        """Scan a folder, build photo records, and reset scene state."""
        loaded_state = _load_folder_state(
            folder,
            metadata_entries=metadata_entries,
            folder_label=folder_label,
            progress_callback=progress_callback,
            read_exif_metadata_fn=_exif_module.read_exif_metadata,
        )
        self.current_folder = loaded_state.current_folder
        self.folder_label = loaded_state.folder_label
        self.photos = loaded_state.photos
        self._photo_map = loaded_state.photo_map
        self.scenes = loaded_state.scenes
        self.scene_source = loaded_state.scene_source
        self.scene_detection_done = loaded_state.scene_detection_done
        if progress_callback:
            progress_callback('Finished loading folder', 100)

    def get_photos(self) -> list[PhotoRecord]:
        """Return a shallow copy of the loaded photo records."""
        return list(self.photos)

    def get_scene_groups(self) -> list[SceneGroup]:
        """Return a shallow copy of the detected scene groups."""
        return list(self.scenes)

    def get_state(self) -> dict[str, Any]:
        """Build the current library state payload for the UI or API."""
        return {
            'folder_path': self.folder_label or None,
            'photos': [photo.to_api_dict() for photo in self.photos],
            'scenes': [scene.to_api_dict() for scene in self.scenes],
            'scene_detection_done': self.scene_detection_done,
        }

    def get_photo(self, photo_id: str) -> PhotoRecord:
        """Look up a photo record by its visible photo id."""
        try:
            return self._photo_map[photo_id]
        except KeyError as exc:
            raise KeyError(f'Unknown photo id: {photo_id}') from exc

    def update_metadata(
            self,
            photo_id: str,
            *,
            rating: Any = None,
            color_label: Any = None,
            flag: Any = None,
            fields: set[str],
    ) -> PhotoRecord:
        """Apply validated metadata updates to a loaded photo record."""
        photo = self.get_photo(photo_id)
        return _validate_and_apply_metadata(
            photo,
            rating=rating,
            color_label=color_label,
            flag=flag,
            fields=fields,
        )

    def export_metadata(self) -> dict[str, dict[str, Any]]:
        """Serialize the current photo metadata for on-disk storage."""
        return _serialize_metadata_entries(self.photos)

    def save_metadata(self) -> None:
        """Write the current photo metadata to the folder JSON file."""
        if self.current_folder is None:
            raise RuntimeError('No folder is currently loaded')

        _write_folder_metadata(
            self.current_folder,
            self.photos,
            self.scenes if self.scene_detection_done else None,
            self.scene_source,
        )

    def detect_scenes(
            self,
            progress_callback: Callable[[str, int], None] | None = None,
    ) -> list[SceneGroup]:
        """Detect scene boundaries across the currently loaded photos."""
        scene_groups = _analysis_scenes_module.detect_scenes(
            self.photos,
            self.get_preview_path,
            progress_callback,
        )
        self._set_scene_groups(scene_groups, scene_source='detected')
        self.scene_detection_done = True
        if self.current_folder is not None:
            self.save_metadata()

        return scene_groups

    def scene_group_photo_ids(self) -> list[list[str]]:
        """Return current scene groups as plain ordered photo-id lists."""
        return [list(scene.photo_ids) for scene in self.scenes]

    def set_scene_group_photo_ids(
            self, groups: list[list[str]], *, scene_source: str | None
    ) -> None:
        """Replace scene groups from plain photo-id lists."""
        if not groups:
            self._set_scene_groups([], scene_source=scene_source)
            return

        _, scenes = _normalize_scene_groups(
            {'scenes': {'source': scene_source, 'groups': groups}},
            [photo.photo_id for photo in self.photos],
        )
        self._set_scene_groups(scenes, scene_source=scene_source)

    def merge_photos_into_scene(self, photo_ids: list[str]) -> None:
        """Merge the selected photo ids into one manually edited scene."""
        ordered_selected = [
            photo.photo_id
            for photo in self.photos
            if photo.photo_id in photo_ids
        ]
        if len(ordered_selected) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return

        existing_groups = (
            self.scene_group_photo_ids()
            if self.scene_detection_done
            else [[photo.photo_id] for photo in self.photos]
        )
        selected = set(ordered_selected)
        next_groups: list[list[str]] = []
        inserted_merged_group = False
        for group in existing_groups:
            remaining_segment: list[str] = []
            for photo_id in group:
                if photo_id not in selected:
                    remaining_segment.append(photo_id)
                    continue

                if remaining_segment:
                    next_groups.append(remaining_segment)
                    remaining_segment = []

                if not inserted_merged_group:
                    next_groups.append(ordered_selected)
                    inserted_merged_group = True

            if remaining_segment:
                next_groups.append(remaining_segment)

        if not inserted_merged_group:
            next_groups.append(ordered_selected)

        self.set_scene_group_photo_ids(next_groups, scene_source='manual')

    def _set_scene_groups(
            self,
            scene_groups: list[SceneGroup],
            *,
            scene_source: str | None,
    ) -> None:
        for photo in self.photos:
            photo.scene_id = None

        self.scenes = scene_groups
        self.scene_source = scene_source
        self.scene_detection_done = bool(scene_groups)
        for scene in self.scenes:
            for photo_id in scene.photo_ids:
                self.get_photo(photo_id).scene_id = scene.scene_id

    def get_preview_path(self, photo_id: str, kind: str) -> Path:
        """Render or reuse a cached preview image for the requested photo."""
        photo = self.get_photo(photo_id)
        return _preview_module.get_preview_path(
            photo, self.current_folder, self.cache_dir, kind
        )
