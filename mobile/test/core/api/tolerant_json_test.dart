import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/tolerant_json.dart';

void main() {
  const json = <String, dynamic>{
    'n': 3,
    'd': 2.5,
    'whole': 4.0,
    'frac': 4.5,
    's': 'text',
    'm': {'k': 1},
    'l': [
      {'a': 1},
      'x',
      2,
      {'b': 2},
    ],
  };

  test('reads values of the right type', () {
    expect(readDouble(json, 'n'), 3.0);
    expect(readDouble(json, 'd'), 2.5);
    expect(readInt(json, 'n'), 3);
    expect(readInt(json, 'whole'), 4);
    expect(readString(json, 's'), 'text');
    expect(readMap(json, 'm'), {'k': 1});
    expect(readMapList(json, 'l'), [
      {'a': 1},
      {'b': 2},
    ]);
  });

  test('missing or wrongly typed values read as null / empty, never throw', () {
    expect(readDouble(json, 'missing'), isNull);
    expect(readDouble(json, 's'), isNull);
    expect(readInt(json, 'frac'), isNull);
    expect(readString(json, 'n'), isNull);
    expect(readMap(json, 'l'), isNull);
    expect(readMapList(json, 'm'), isEmpty);
    expect(readDouble(null, 'n'), isNull);
    expect(readMapList(null, 'l'), isEmpty);
  });
}
