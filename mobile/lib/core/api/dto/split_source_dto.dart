import '../tolerant_json.dart';

/// Split library (issue #143, API level 4): a git repo of split templates the
/// user subscribes to, mirroring the server's SplitSourceOut. Read
/// tolerantly: only `id` is required, everything else has a default, so a
/// newer server's changes can't break the Library screen.
class SplitSourceDto {
  final String id;
  final String name;
  final String url;
  final String ref;
  final String path;
  final bool enabled;
  final bool isDefault;
  final bool hasToken;
  final DateTime? lastSyncedAt;
  final String? lastError;
  final List<String> warnings;
  final List<SplitSourceFolderDto> folders;

  const SplitSourceDto({
    required this.id,
    required this.name,
    this.url = '',
    this.ref = '',
    this.path = '',
    this.enabled = true,
    this.isDefault = false,
    this.hasToken = false,
    this.lastSyncedAt,
    this.lastError,
    this.warnings = const [],
    this.folders = const [],
  });

  static SplitSourceDto? fromJson(Map<String, dynamic> json) {
    final id = readString(json, 'id');
    if (id == null) return null;
    final synced = readString(json, 'last_synced_at');
    return SplitSourceDto(
      id: id,
      name: readString(json, 'name') ?? readString(json, 'url') ?? 'Split repo',
      url: readString(json, 'url') ?? '',
      ref: readString(json, 'ref') ?? '',
      path: readString(json, 'path') ?? '',
      enabled: json['enabled'] != false,
      isDefault: json['is_default'] == true,
      hasToken: json['has_token'] == true,
      lastSyncedAt: synced == null ? null : DateTime.tryParse(synced),
      lastError: readString(json, 'last_error'),
      warnings: switch (json['warnings']) {
        final List<dynamic> values => values.whereType<String>().toList(),
        _ => const [],
      },
      folders: [
        for (final folder in readMapList(json, 'folders')) ?SplitSourceFolderDto.fromJson(folder),
      ],
    );
  }
}

class SplitSourceFolderDto {
  final String id;
  final String name;
  final String? description;
  final bool enabled;
  final int templateCount;

  const SplitSourceFolderDto({
    required this.id,
    required this.name,
    this.description,
    this.enabled = true,
    this.templateCount = 0,
  });

  static SplitSourceFolderDto? fromJson(Map<String, dynamic> json) {
    final id = readString(json, 'id');
    if (id == null) return null;
    return SplitSourceFolderDto(
      id: id,
      name: readString(json, 'name') ?? readString(json, 'folder') ?? 'Folder',
      description: readString(json, 'description'),
      enabled: json['enabled'] != false,
      templateCount: readInt(json, 'template_count') ?? 0,
    );
  }
}

/// GET /api/v1/split-sources.
class SplitSourceListDto {
  final List<SplitSourceDto> sources;

  /// Whether this server lets users add their own repos.
  final bool canAdd;

  const SplitSourceListDto({required this.sources, this.canAdd = false});

  factory SplitSourceListDto.fromJson(Map<String, dynamic> json) => SplitSourceListDto(
    sources: [for (final source in readMapList(json, 'sources')) ?SplitSourceDto.fromJson(source)],
    canAdd: json['can_add'] == true,
  );
}

/// The result of adding or syncing a repo. A failed fetch is `ok: false`
/// with [error], not an HTTP error.
class SplitSourceSyncDto {
  final bool ok;
  final int added;
  final int updated;
  final int removed;
  final String? error;
  final SplitSourceDto? source;

  const SplitSourceSyncDto({
    required this.ok,
    this.added = 0,
    this.updated = 0,
    this.removed = 0,
    this.error,
    this.source,
  });

  factory SplitSourceSyncDto.fromJson(Map<String, dynamic> json) {
    final source = readMap(json, 'source');
    return SplitSourceSyncDto(
      ok: json['ok'] == true,
      added: readInt(json, 'added') ?? 0,
      updated: readInt(json, 'updated') ?? 0,
      removed: readInt(json, 'removed') ?? 0,
      error: readString(json, 'error'),
      source: source == null ? null : SplitSourceDto.fromJson(source),
    );
  }

  /// "3 added, 1 updated", or "no changes".
  String get summary {
    final parts = [
      if (added > 0) '$added added',
      if (updated > 0) '$updated updated',
      if (removed > 0) '$removed removed',
    ];
    return parts.isEmpty ? 'no changes' : parts.join(', ');
  }
}

/// Changes to a split repo (PATCH /api/v1/split-sources/{id}); null fields
/// are left out, so they stay as they are.
class SplitSourceUpdateDto {
  final bool? enabled;
  final String? name;
  final String? ref;
  final String? path;
  final String? token;
  final bool clearToken;

  const SplitSourceUpdateDto({
    this.enabled,
    this.name,
    this.ref,
    this.path,
    this.token,
    this.clearToken = false,
  });

  Map<String, dynamic> toJson() => {
    'enabled': ?enabled,
    'name': ?name,
    'ref': ?ref,
    'path': ?path,
    'token': ?token,
    if (clearToken) 'clear_token': true,
  };
}

/// A new split repo (POST /api/v1/split-sources).
class SplitSourceCreateDto {
  final String url;
  final String? hostKind;
  final String ref;
  final String path;
  final String? name;
  final String? token;

  const SplitSourceCreateDto({
    required this.url,
    this.hostKind,
    this.ref = 'main',
    this.path = 'splits',
    this.name,
    this.token,
  });

  Map<String, dynamic> toJson() => {
    'url': url.trim(),
    'host_kind': ?hostKind,
    'ref': ref.trim().isEmpty ? 'main' : ref.trim(),
    'path': path.trim(),
    if (name != null && name!.trim().isNotEmpty) 'name': name!.trim(),
    if (token != null && token!.trim().isNotEmpty) 'token': token!.trim(),
  };
}

/// POST /api/v1/split-configs/import.
class SplitImportResultDto {
  final int created;
  final int updated;
  final List<String> renamed;
  final List<String> errors;

  const SplitImportResultDto({
    this.created = 0,
    this.updated = 0,
    this.renamed = const [],
    this.errors = const [],
  });

  factory SplitImportResultDto.fromJson(Map<String, dynamic> json) {
    List<String> strings(String key) => switch (json[key]) {
      final List<dynamic> values => values.whereType<String>().toList(),
      _ => const [],
    };
    return SplitImportResultDto(
      created: readInt(json, 'created') ?? 0,
      updated: readInt(json, 'updated') ?? 0,
      renamed: strings('renamed'),
      errors: strings('errors'),
    );
  }
}
