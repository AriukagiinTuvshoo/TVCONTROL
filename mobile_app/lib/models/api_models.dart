// Data transfer models matching FastAPI Pydantic v2 schemas 1:1.

class TimeStateDto {
  const TimeStateDto({
    required this.state,
    required this.reason,
    required this.allowedSecondsToday,
    required this.usedSecondsToday,
    required this.overrideSecondsToday,
    required this.remainingSecondsToday,
    required this.effectiveRemainingSeconds,
    this.activeWarningMinutes,
  });

  factory TimeStateDto.fromJson(Map<String, dynamic> json) {
    return TimeStateDto(
      state: (json['state'] as String?) ?? 'ALLOW',
      reason: (json['reason'] as String?) ?? '',
      allowedSecondsToday: (json['allowed_seconds_today'] as num?)?.toInt() ?? 0,
      usedSecondsToday: (json['used_seconds_today'] as num?)?.toInt() ?? 0,
      overrideSecondsToday:
          (json['override_seconds_today'] as num?)?.toInt() ?? 0,
      remainingSecondsToday:
          (json['remaining_seconds_today'] as num?)?.toInt() ?? 0,
      effectiveRemainingSeconds:
          (json['effective_remaining_seconds'] as num?)?.toInt() ?? 0,
      activeWarningMinutes: (json['active_warning_minutes'] as num?)?.toInt(),
    );
  }

  final String state;
  final String reason;
  final int allowedSecondsToday;
  final int usedSecondsToday;
  final int overrideSecondsToday;
  final int remainingSecondsToday;
  final int effectiveRemainingSeconds;
  final int? activeWarningMinutes;

  int get allowedMinutes => (allowedSecondsToday / 60).round();
  int get usedMinutes => (usedSecondsToday / 60).round();
  int get overrideMinutes => (overrideSecondsToday / 60).round();
  int get remainingMinutes => (remainingSecondsToday / 60).ceil();
}

class ChildDto {
  ChildDto({
    required this.id,
    required this.familyId,
    required this.nickname,
    required this.ageGroup,
    required this.avatarKey,
    required this.isActive,
    required this.dailyLimitMinutes,
    required this.isInstantLocked,
    this.policyId,
    this.timeState,
  });

  factory ChildDto.fromJson(Map<String, dynamic> json) {
    return ChildDto(
      id: json['id'] as String,
      familyId: json['family_id'] as String,
      nickname: json['nickname'] as String,
      ageGroup: (json['age_group'] as String?) ?? '7-9',
      avatarKey: (json['avatar_key'] as String?) ?? 'fox',
      isActive: (json['is_active'] as bool?) ?? true,
      policyId: json['policy_id'] as String?,
      dailyLimitMinutes: (json['daily_limit_minutes'] as num?)?.toInt() ?? 90,
      isInstantLocked: (json['is_instant_locked'] as bool?) ?? false,
      timeState: json['time_state'] != null
          ? TimeStateDto.fromJson(json['time_state'] as Map<String, dynamic>)
          : null,
    );
  }

  final String id;
  final String familyId;
  String nickname;
  String ageGroup;
  String avatarKey;
  final bool isActive;
  final String? policyId;
  int dailyLimitMinutes;
  bool isInstantLocked;
  TimeStateDto? timeState;

  int get totalAllowedMinutes =>
      timeState?.allowedMinutes ?? dailyLimitMinutes;
  int get usedMinutesToday => timeState?.usedMinutes ?? 0;
  int get remainingMinutes =>
      timeState?.remainingMinutes ?? dailyLimitMinutes;
  String get engineState =>
      isInstantLocked ? 'BLOCK' : (timeState?.state ?? 'ALLOW');
}

class ScheduleItemDto {
  ScheduleItemDto({
    required this.dayOfWeek,
    required this.isSchoolDay,
    required this.startTime,
    required this.endTime,
    required this.isEnabled,
  });

  factory ScheduleItemDto.fromJson(Map<String, dynamic> json) {
    String trimTime(String raw) => raw.length >= 5 ? raw.substring(0, 5) : raw;
    return ScheduleItemDto(
      dayOfWeek: (json['day_of_week'] as num).toInt(),
      isSchoolDay: (json['is_school_day'] as bool?) ?? true,
      startTime: trimTime((json['start_time'] as String?) ?? '08:00'),
      endTime: trimTime((json['end_time'] as String?) ?? '21:00'),
      isEnabled: (json['is_enabled'] as bool?) ?? true,
    );
  }

  final int dayOfWeek;
  bool isSchoolDay;
  String startTime;
  String endTime;
  bool isEnabled;

  Map<String, dynamic> toJson() => {
        'day_of_week': dayOfWeek,
        'is_school_day': isSchoolDay,
        'start_time': startTime.length == 5 ? '$startTime:00' : startTime,
        'end_time': endTime.length == 5 ? '$endTime:00' : endTime,
        'is_enabled': isEnabled,
      };
}

class AllowedAppDto {
  AllowedAppDto({
    required this.packageName,
    required this.appLabel,
    required this.category,
    required this.isAllowed,
  });

  factory AllowedAppDto.fromJson(Map<String, dynamic> json) {
    return AllowedAppDto(
      packageName: json['package_name'] as String,
      appLabel: json['app_label'] as String,
      category: (json['category'] as String?) ?? 'EDUCATION',
      isAllowed: (json['is_allowed'] as bool?) ?? true,
    );
  }

  final String packageName;
  final String appLabel;
  final String category;
  bool isAllowed;

  Map<String, dynamic> toJson() => {
        'package_name': packageName,
        'app_label': appLabel,
        'category': category,
        'is_allowed': isAllowed,
      };
}

class PolicyDto {
  PolicyDto({
    required this.id,
    required this.familyId,
    required this.childId,
    required this.dailyLimitMinutes,
    required this.weekendBonusMinutes,
    required this.warningMinutes,
    required this.enforceWhitelist,
    required this.isInstantLocked,
    required this.version,
    required this.schedules,
    required this.allowedApps,
    this.timeState,
  });

  factory PolicyDto.fromJson(Map<String, dynamic> json) {
    return PolicyDto(
      id: json['id'] as String,
      familyId: json['family_id'] as String,
      childId: json['child_id'] as String,
      dailyLimitMinutes: (json['daily_limit_minutes'] as num).toInt(),
      weekendBonusMinutes: (json['weekend_bonus_minutes'] as num).toInt(),
      warningMinutes: ((json['warning_minutes'] as List<dynamic>?) ?? [15, 5, 1])
          .map((e) => (e as num).toInt())
          .toList(),
      enforceWhitelist: (json['enforce_whitelist'] as bool?) ?? true,
      isInstantLocked: (json['is_instant_locked'] as bool?) ?? false,
      version: (json['version'] as num?)?.toInt() ?? 1,
      schedules: ((json['schedules'] as List<dynamic>?) ?? [])
          .map((e) => ScheduleItemDto.fromJson(e as Map<String, dynamic>))
          .toList(),
      allowedApps: ((json['allowed_apps'] as List<dynamic>?) ?? [])
          .map((e) => AllowedAppDto.fromJson(e as Map<String, dynamic>))
          .toList(),
      timeState: json['time_state'] != null
          ? TimeStateDto.fromJson(json['time_state'] as Map<String, dynamic>)
          : null,
    );
  }

  final String id;
  final String familyId;
  final String childId;
  int dailyLimitMinutes;
  int weekendBonusMinutes;
  List<int> warningMinutes;
  bool enforceWhitelist;
  bool isInstantLocked;
  int version;
  List<ScheduleItemDto> schedules;
  List<AllowedAppDto> allowedApps;
  TimeStateDto? timeState;
}

class DeviceDto {
  const DeviceDto({
    required this.id,
    required this.deviceName,
    required this.deviceType,
    required this.hardwareUid,
    required this.status,
    this.familyId,
    this.activeChildId,
  });

  factory DeviceDto.fromJson(Map<String, dynamic> json) {
    return DeviceDto(
      id: json['id'] as String,
      familyId: json['family_id'] as String?,
      activeChildId: json['active_child_id'] as String?,
      deviceName: json['device_name'] as String,
      deviceType: (json['device_type'] as String?) ?? 'FAMILYSCREEN_BOX',
      hardwareUid: json['hardware_uid'] as String,
      status: (json['status'] as String?) ?? 'ONLINE',
    );
  }

  final String id;
  final String? familyId;
  final String? activeChildId;
  final String deviceName;
  final String deviceType;
  final String hardwareUid;
  final String status;
}

class DevicePairInitDto {
  const DevicePairInitDto({
    required this.deviceId,
    required this.pairingCode,
    required this.qrPayload,
  });

  factory DevicePairInitDto.fromJson(Map<String, dynamic> json) {
    return DevicePairInitDto(
      deviceId: json['device_id'] as String,
      pairingCode: json['pairing_code'] as String,
      qrPayload: json['qr_payload'] as String,
    );
  }

  final String deviceId;
  final String pairingCode;
  final String qrPayload;
}

class DailyUsageItemDto {
  const DailyUsageItemDto({
    required this.usageDate,
    required this.allowedMinutes,
    required this.usedMinutes,
    required this.overrideMinutes,
  });

  factory DailyUsageItemDto.fromJson(Map<String, dynamic> json) {
    return DailyUsageItemDto(
      usageDate: json['usage_date'] as String,
      allowedMinutes: (json['allowed_minutes'] as num).toInt(),
      usedMinutes: (json['used_minutes'] as num).toInt(),
      overrideMinutes: (json['override_minutes'] as num).toInt(),
    );
  }

  final String usageDate;
  final int allowedMinutes;
  final int usedMinutes;
  final int overrideMinutes;
}

class AppBreakdownItemDto {
  const AppBreakdownItemDto({
    required this.packageName,
    required this.usedMinutes,
  });

  factory AppBreakdownItemDto.fromJson(Map<String, dynamic> json) {
    return AppBreakdownItemDto(
      packageName: json['package_name'] as String,
      usedMinutes: (json['used_minutes'] as num).toInt(),
    );
  }

  final String packageName;
  final int usedMinutes;
}

class UsageReportDto {
  const UsageReportDto({
    required this.familyId,
    required this.childId,
    required this.childNickname,
    required this.days,
    required this.totalUsedMinutes,
    required this.dailyItems,
    required this.appBreakdown,
  });

  factory UsageReportDto.fromJson(Map<String, dynamic> json) {
    return UsageReportDto(
      familyId: json['family_id'] as String,
      childId: json['child_id'] as String,
      childNickname: json['child_nickname'] as String,
      days: (json['days'] as num).toInt(),
      totalUsedMinutes: (json['total_used_minutes'] as num).toInt(),
      dailyItems: ((json['daily_items'] as List<dynamic>?) ?? [])
          .map((e) => DailyUsageItemDto.fromJson(e as Map<String, dynamic>))
          .toList(),
      appBreakdown: ((json['app_breakdown'] as List<dynamic>?) ?? [])
          .map((e) => AppBreakdownItemDto.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }

  final String familyId;
  final String childId;
  final String childNickname;
  final int days;
  final int totalUsedMinutes;
  final List<DailyUsageItemDto> dailyItems;
  final List<AppBreakdownItemDto> appBreakdown;
}
