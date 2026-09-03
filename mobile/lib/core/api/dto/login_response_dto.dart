import 'device_dto.dart';
import 'user_dto.dart';

/// Mirrors the server's LoginResponse schema. The token is shown once and
/// never returned again by the server — AuthService is responsible for
/// storing it (secure storage) as soon as this DTO is received.
class LoginResponseDto {
  final String token;
  final DeviceDto device;
  final UserDto user;

  const LoginResponseDto({
    required this.token,
    required this.device,
    required this.user,
  });

  factory LoginResponseDto.fromJson(Map<String, dynamic> json) => LoginResponseDto(
        token: json['token'] as String,
        device: DeviceDto.fromJson(json['device'] as Map<String, dynamic>),
        user: UserDto.fromJson(json['user'] as Map<String, dynamic>),
      );
}
