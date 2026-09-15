/// Mirrors the server's TagOut schema.
class TagDto {
  final String id;
  final String name;

  const TagDto({required this.id, required this.name});

  factory TagDto.fromJson(Map<String, dynamic> json) =>
      TagDto(id: json['id'] as String, name: json['name'] as String);
}
