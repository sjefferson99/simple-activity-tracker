/// Mirrors the server's UserOut schema (server/app/api/v1/schemas.py).
class UserDto {
  final String id;
  final String email;
  final String displayName;
  final bool isAdmin;

  const UserDto({
    required this.id,
    required this.email,
    required this.displayName,
    required this.isAdmin,
  });

  factory UserDto.fromJson(Map<String, dynamic> json) => UserDto(
        id: json['id'] as String,
        email: json['email'] as String,
        displayName: json['display_name'] as String,
        isAdmin: json['is_admin'] as bool,
      );
}
