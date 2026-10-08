class LiveUtteranceBuffer {
  String _committed = '';
  String _active = '';

  String get text {
    final parts = <String>[
      if (_committed.trim().isNotEmpty) _committed.trim(),
      if (_active.trim().isNotEmpty) _active.trim(),
    ];
    return parts.join(' ').trim();
  }

  bool get isEmpty => text.isEmpty;
  bool get hasCommitted => _committed.trim().isNotEmpty;
  bool get hasActive => _active.trim().isNotEmpty;

  void appendDelta(String delta) {
    if (delta.isEmpty) return;
    _active += delta;
  }

  String complete(String transcript) {
    final completed = transcript.trim().isNotEmpty
        ? transcript.trim()
        : _active.trim();

    if (completed.isNotEmpty) {
      if (_committed.trim().isEmpty) {
        _committed = completed;
      } else if (!_committed.trim().endsWith(completed)) {
        _committed = '${_committed.trim()} $completed';
      }
    }

    _active = '';
    return text;
  }

  void consume(String processedText) {
    final processed = processedText.trim();
    if (processed.isEmpty) return;

    final current = text;
    if (current == processed) {
      clear();
      return;
    }

    if (current.startsWith(processed)) {
      final remaining = current
          .substring(processed.length)
          .trimLeft();
      _committed = remaining;
      _active = '';
    }
  }

  void clear() {
    _committed = '';
    _active = '';
  }
}
