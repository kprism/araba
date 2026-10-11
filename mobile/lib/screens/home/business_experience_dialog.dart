import 'package:flutter/material.dart';

/// The dialog owns its editable state until Flutter finishes disposing the
/// route. Do not dispose a TextEditingController immediately after showDialog
/// returns: the dialog may still be animating out with a focused TextField.
class BusinessExperienceDialog extends StatefulWidget {
  const BusinessExperienceDialog({
    super.key,
    required this.businessName,
  });

  final String businessName;

  @override
  State<BusinessExperienceDialog> createState() =>
      _BusinessExperienceDialogState();
}

class _BusinessExperienceDialogState extends State<BusinessExperienceDialog> {
  String _experience = '';

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('${widget.businessName} 이용 경험'),
      content: TextField(
        autofocus: true,
        minLines: 3,
        maxLines: 6,
        onChanged: (value) => _experience = value,
        decoration: const InputDecoration(
          hintText: '예: 주차장은 좁았고 15분 정도 기다렸지만 설명은 자세했어요.',
          border: OutlineInputBorder(),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('취소'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_experience.trim()),
          child: const Text('경험 저장'),
        ),
      ],
    );
  }
}
