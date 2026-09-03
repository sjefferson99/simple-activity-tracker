/// Mirrors the server's AnalysisOut schema. `result` is left as a raw JSON
/// map — its shape (splits, best efforts, series, …) is defined entirely
/// server-side (docs/WEB-PLAN.md §5.4) and the app only needs to display a
/// few fields from it, not model the whole thing.
class AnalysisDto {
  final String status;
  final Map<String, dynamic>? result;

  const AnalysisDto({required this.status, required this.result});

  bool get isDone => status == 'done';
  bool get isPending => status == 'pending';
  bool get isFailed => status == 'failed';

  factory AnalysisDto.fromJson(Map<String, dynamic> json) => AnalysisDto(
        status: json['status'] as String,
        result: json['result'] as Map<String, dynamic>?,
      );
}
