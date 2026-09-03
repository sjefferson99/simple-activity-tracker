/// Mirrors the server's DeviceOut schema (server/app/api/v1/schemas.py).
class DeviceDto {
  final String id;
  final String name;
  final DateTime createdAt;
  final DateTime? lastUsedAt;

  const DeviceDto({
    required this.id,
    required this.name,
    required this.createdAt,
    required this.lastUsedAt,
  });

  factory DeviceDto.fromJson(Map<String, dynamic> json) => DeviceDto(
        id: json['id'] as String,
        name: json['name'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        lastUsedAt: json['last_used_at'] == null
            ? null
            : DateTime.parse(json['last_used_at'] as String),
      );
}
