import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:just_audio/just_audio.dart';

const appName = '橘味儿音乐';
const appVersion = '3.3.0';
const mobileAiServer = 'https://api.db0888.com';
const accent = Color(0xFFFF7A18);
const orangeSoft = Color(0xFFFFA23D);
const violet = Color(0xFF8F3DFF);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = AppStore();
  await store.load();
  runApp(JuweierMusicApp(store: store));
}

class PipelineJob {
  PipelineJob({
    required this.id,
    required this.fileName,
    required this.path,
    required this.size,
    required this.createdAt,
    this.status = '等待处理',
    this.stage = '导入',
    this.progress = 0,
    this.error = '',
    this.serverJobId = '',
    this.originalKey = 'C',
    this.semitones = 0,
    this.arrangementMode = '乐队现场版',
    this.libraryId = 0,
    Map<String, String>? artifacts,
  }) : artifacts = artifacts ?? <String, String>{};

  final String id;
  final String fileName;
  final String path;
  final int size;
  final int createdAt;
  String status;
  String stage;
  double progress;
  String error;
  String serverJobId;
  String originalKey;
  int semitones;
  String arrangementMode;
  int libraryId;
  Map<String, String> artifacts;

  bool get isRunning => status == '处理中' || status == '上传中';
  bool get isDone => status == '完成';

  Map<String, dynamic> toJson() => {
        'id': id,
        'file_name': fileName,
        'path': path,
        'size': size,
        'created_at': createdAt,
        'status': status,
        'stage': stage,
        'progress': progress,
        'error': error,
        'server_job_id': serverJobId,
        'original_key': originalKey,
        'semitones': semitones,
        'arrangement_mode': arrangementMode,
        'library_id': libraryId,
        'artifacts': artifacts,
      };

  factory PipelineJob.fromJson(Map<String, dynamic> json) {
    final rawArtifacts = json['artifacts'];
    return PipelineJob(
      id: '${json['id'] ?? ''}',
      fileName: '${json['file_name'] ?? '未命名歌曲'}',
      path: '${json['path'] ?? ''}',
      size: (json['size'] as num?)?.toInt() ?? 0,
      createdAt: (json['created_at'] as num?)?.toInt() ?? 0,
      status: '${json['status'] ?? '等待处理'}',
      stage: '${json['stage'] ?? '导入'}',
      progress: ((json['progress'] as num?)?.toDouble() ?? 0).clamp(0, 1).toDouble(),
      error: '${json['error'] ?? ''}',
      serverJobId: '${json['server_job_id'] ?? ''}',
      originalKey: '${json['original_key'] ?? 'C'}',
      semitones: ((json['semitones'] as num?)?.toInt() ?? 0).clamp(-12, 12).toInt(),
      arrangementMode: '${json['arrangement_mode'] ?? '乐队现场版'}',
      libraryId: (json['library_id'] as num?)?.toInt() ?? 0,
      artifacts: rawArtifacts is Map
          ? rawArtifacts.map((key, value) => MapEntry('$key', '$value'))
          : <String, String>{},
    );
  }
}

class LibrarySong {
  const LibrarySong({required this.id, required this.title, required this.artist, required this.album, required this.artistInitial, required this.category, required this.audioUrl, required this.coverUrl, required this.lyricsUrl, required this.tags, required this.language, required this.genre, required this.processingStatus, required this.publishStatus, required this.artifacts});
  final int id;
  final String title;
  final String artist;
  final String album;
  final String artistInitial;
  final String category;
  final String audioUrl;
  final String coverUrl;
  final String lyricsUrl;
  final List<String> tags;
  final String language;
  final String genre;
  final String processingStatus;
  final String publishStatus;
  final Map<String, String> artifacts;
  bool get isAiReady => processingStatus == '已完成' && artifacts.isNotEmpty;

  factory LibrarySong.fromJson(Map<String, dynamic> json) => LibrarySong(
        id: (json['id'] as num?)?.toInt() ?? 0,
        title: '${json['title'] ?? '未命名歌曲'}',
        artist: '${json['artist'] ?? '未知歌手'}',
        album: '${json['album'] ?? ''}',
        artistInitial: '${json['artist_initial'] ?? '#'}'.toUpperCase(),
        category: '${json['category'] ?? '本地导入'}',
        audioUrl: '${json['audio_url'] ?? ''}',
        coverUrl: '${json['cover_url'] ?? ''}',
        lyricsUrl: '${json['lyrics_url'] ?? ''}',
        tags: (json['tags'] is List ? json['tags'] as List : const []).map((e) => '$e').toList(),
        language: '${json['language'] ?? '其他'}',
        genre: '${json['genre'] ?? '流行'}',
        processingStatus: '${json['processing_status'] ?? '待处理'}',
        publishStatus: '${json['publish_status'] ?? '已发布'}',
        artifacts: json['artifacts'] is Map
            ? (json['artifacts'] as Map).map((key, value) => MapEntry('$key', '$value'))
            : <String, String>{},
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'artist': artist,
        'album': album,
        'artist_initial': artistInitial,
        'category': category,
        'audio_url': audioUrl,
        'cover_url': coverUrl,
        'lyrics_url': lyricsUrl,
        'tags': tags,
        'language': language,
        'genre': genre,
        'processing_status': processingStatus,
        'publish_status': publishStatus,
        'artifacts': artifacts,
      };
}

class ImportReport {
  const ImportReport(this.added, this.skipped);
  final int added;
  final int skipped;
}

class CommunityMessage {
  const CommunityMessage({required this.id, required this.nickname, required this.content, required this.createdAt});
  final int id;
  final String nickname;
  final String content;
  final double createdAt;

  factory CommunityMessage.fromJson(Map<String, dynamic> json) => CommunityMessage(
        id: (json['id'] as num?)?.toInt() ?? 0,
        nickname: '${json['nickname'] ?? json['username'] ?? '内测用户'}',
        content: '${json['content'] ?? ''}',
        createdAt: (json['created_at'] as num?)?.toDouble() ?? 0,
      );
}

class AppStore extends ChangeNotifier {
  // Keep the v3 storage key so existing v3.0 tasks survive the upgrade.
  static const _jobsKey = 'juweier_jobs_v300';
  static const _serverKey = 'juweier_server';
  static const _tokenKey = 'juweier_token';
  static const _accountTokenKey = 'juweier_account_token';
  static const _usernameKey = 'juweier_username';
  static const _nicknameKey = 'juweier_nickname';
  // Keep the existing catalog key so v3.2.6 users see cached songs immediately.
  static const _catalogKey = 'juweier_catalog_v326';
  static const _catalogVersionKey = 'juweier_catalog_version_v330';
  static const _catalogCategoriesKey = 'juweier_catalog_categories_v330';
  static const _guestKey = 'juweier_guest_testing';

  SharedPreferences? _prefs;
  final List<PipelineJob> jobs = [];
  final List<CommunityMessage> communityMessages = [];
  final List<LibrarySong> catalog = [];
  int catalogVersion = 0;
  List<String> catalogCategories = const ['全部','推荐','新歌','华语','粤语','欧美','日韩','流行','摇滚','民谣','古风','电子','DJ','经典','轻音乐','情歌','儿童','车载','KTV','广场舞','影视','游戏','运动','抖音流行','酷狗排行榜','AI已完成','有歌词','有乐谱','有分轨'];
  String serverBase = mobileAiServer;
  String apiToken = '';
  String accountToken = '';
  String username = '';
  String nickname = '';
  String phone = '';
  String avatarUrl = '';
  String gender = '保密';
  String bio = '';
  String origin = '';
  String address = '';
  String wechat = '';
  bool guestMode = false;
  String accountState = '未登录';
  String serverState = '待检测';
  String serverDetail = 'AI 服务由应用自动连接';

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    serverBase = mobileAiServer;
    apiToken = '';
    accountToken = _prefs?.getString(_accountTokenKey) ?? '';
    username = _prefs?.getString(_usernameKey) ?? '';
    nickname = _prefs?.getString(_nicknameKey) ?? '';
    guestMode = _prefs?.getBool(_guestKey) ?? false;
    accountState = accountToken.isEmpty ? '未登录' : '已登录';
    final rawCatalog = _prefs?.getString(_catalogKey);
    catalogVersion = _prefs?.getInt(_catalogVersionKey) ?? 0;
    final savedCategories = _prefs?.getStringList(_catalogCategoriesKey);
    if (savedCategories != null && savedCategories.isNotEmpty) catalogCategories = savedCategories;
    if (rawCatalog != null && rawCatalog.isNotEmpty) {
      try {
        final rows = jsonDecode(rawCatalog) as List<dynamic>;
        catalog.addAll(rows.map((row) => LibrarySong.fromJson(Map<String, dynamic>.from(row as Map))));
      } catch (_) {
        catalog.clear();
      }
    }
    final raw = _prefs?.getString(_jobsKey);
    if (raw != null && raw.isNotEmpty) {
      try {
        final rows = jsonDecode(raw) as List<dynamic>;
        for (final row in rows) {
          final job = PipelineJob.fromJson(Map<String, dynamic>.from(row as Map));
          if (job.isRunning) {
            job.status = '等待继续';
            job.stage = '上次任务中断，可重新提交或继续查询';
          }
          jobs.add(job);
        }
      } catch (_) {
        jobs.clear();
      }
    }
    unawaited(testServer());
    unawaited(refreshCatalog(silent: true));
    if (accountToken.isNotEmpty) unawaited(refreshProfile());
  }

  Future<void> _save() async {
    await _prefs?.setString(_jobsKey, jsonEncode(jobs.map((e) => e.toJson()).toList()));
    await _prefs?.setString(_accountTokenKey, accountToken);
    await _prefs?.setString(_usernameKey, username);
    await _prefs?.setString(_nicknameKey, nickname);
    await _prefs?.setBool(_guestKey, guestMode);
    await _prefs?.setString(_catalogKey, jsonEncode(catalog.map((e) => e.toJson()).toList()));
    await _prefs?.setInt(_catalogVersionKey, catalogVersion);
    await _prefs?.setStringList(_catalogCategoriesKey, catalogCategories);
  }

  Future<void> saveServer(String base, String token) async {
    serverBase = mobileAiServer;
    apiToken = '';
    serverState = '待检测';
    serverDetail = 'AI 服务由应用自动连接';
    await _save();
    notifyListeners();
  }

  Future<ImportReport> addFiles(List<PlatformFile> files) async {
    final existing = jobs.map((e) => e.path.toLowerCase()).toSet();
    var added = 0;
    var skipped = 0;
    for (final file in files) {
      final path = file.path;
      if (path == null || path.isEmpty || existing.contains(path.toLowerCase())) {
        skipped++;
        continue;
      }
      final now = DateTime.now().microsecondsSinceEpoch;
      final fileSize = await file.length();
      jobs.insert(
        0,
        PipelineJob(
          id: 'local-$now-$added',
          fileName: file.name,
          path: path,
          size: fileSize,
          createdAt: DateTime.now().millisecondsSinceEpoch,
        ),
      );
      existing.add(path.toLowerCase());
      added++;
    }
    await _save();
    notifyListeners();
    return ImportReport(added, skipped);
  }

  Future<void> refreshCatalog({String query = '', String category = '全部', bool silent = false}) async {
    if (serverBase.isEmpty) return;
    try {
      final client = ApiClient(serverBase, accountToken.isNotEmpty ? accountToken : apiToken);
      // Keep one complete offline catalog. Search and category filters are
      // applied locally so a filtered screen never overwrites the startup cache.
      final result = await client.library('', '全部', since: catalog.isNotEmpty ? catalogVersion : 0);
      if (result['not_modified'] == true) return;
      final rows = result['songs'];
      final incoming = rows is List
          ? rows.map((row) => LibrarySong.fromJson(Map<String, dynamic>.from(row as Map))).toList()
          : const <LibrarySong>[];
      if (result['incremental'] == true) {
        final deleted = (result['deleted_ids'] is List ? result['deleted_ids'] as List : const [])
            .map((value) => (value as num).toInt()).toSet();
        final merged = <int, LibrarySong>{for (final song in catalog) song.id: song};
        for (final id in deleted) merged.remove(id);
        for (final song in incoming) merged[song.id] = song;
        catalog
          ..clear()
          ..addAll(merged.values);
      } else {
        catalog
          ..clear()
          ..addAll(incoming);
      }
      catalogVersion = (result['catalog_version'] as num?)?.toInt() ?? catalogVersion;
      final categories = result['categories'];
      if (categories is List && categories.isNotEmpty) {
        catalogCategories = categories.map((e) => '$e').toList();
      }
      await _save();
      notifyListeners();
    } catch (_) {
      if (!silent) rethrow;
    }
  }

  Future<Map<String, dynamic>> importPublicLink(String url) async {
    if (serverBase.isEmpty) throw const FormatException('请先配置 AI 服务器地址');
    final client = ApiClient(serverBase, accountToken.isNotEmpty ? accountToken : apiToken);
    return client.importLink(url.trim());
  }

  Future<Map<String, dynamic>> generateLyrics(Map<String, dynamic> payload) {
    if (serverBase.isEmpty) throw const FormatException('AI 服务暂不可用');
    return ApiClient(serverBase, accountToken.isNotEmpty ? accountToken : apiToken)
        .generateLyrics(payload);
  }

  Future<Map<String, dynamic>> submitFeedback(Map<String, dynamic> payload) {
    if (serverBase.isEmpty) throw const FormatException('AI 服务暂不可用');
    return ApiClient(serverBase, accountToken.isNotEmpty ? accountToken : apiToken)
        .submitFeedback(payload);
  }

  Future<PipelineJob> addLibrarySong(LibrarySong song) async {
    final existing = jobs.where((job) => job.libraryId == song.id);
    if (existing.isNotEmpty) return existing.first;
    final job = PipelineJob(
      id: 'library-${song.id}-${DateTime.now().microsecondsSinceEpoch}',
      fileName: '${song.artist} - ${song.title}', path: '', size: 0,
      createdAt: DateTime.now().millisecondsSinceEpoch, libraryId: song.id,
    );
    jobs.insert(0, job);
    await _save();
    notifyListeners();
    return job;
  }

  Future<void> removeJob(PipelineJob job) async {
    if (job.isRunning) return;
    jobs.removeWhere((item) => item.id == job.id);
    await _save();
    notifyListeners();
  }

  Future<void> clearFinishedJobs() async {
    jobs.removeWhere((job) => job.status == '完成' || job.status == '失败');
    await _save();
    notifyListeners();
  }

  Future<void> testServer() async {
    if (serverBase.isEmpty) {
      serverState = '未配置';
      serverDetail = '请在设置中填写服务器地址';
      notifyListeners();
      return;
    }
    serverState = '检测中';
    serverDetail = serverBase;
    notifyListeners();
    try {
      final token = accountToken.isNotEmpty ? accountToken : apiToken;
      final result = await ApiClient(serverBase, token).health();
      final ready = result['processing_ready'] == true;
      serverState = ready ? '在线 · AI就绪' : '在线 · AI未就绪';
      final runtime = result['runtime'];
      final issues = runtime is Map && runtime['issues'] is List
          ? (runtime['issues'] as List).join('；')
          : '';
      serverDetail = '${result['gpu'] ?? result['device'] ?? '服务器可用'} · ${result['catalog_count'] ?? catalog.length} 首歌曲'
          '${ready || issues.isEmpty ? '' : ' · $issues'}';
    } catch (error) {
      serverState = '离线';
      serverDetail = '$error';
    }
    notifyListeners();
  }

  Future<void> startJob(PipelineJob job) async {
    if (job.isRunning) return;
    if (serverBase.isEmpty) {
      job.status = '失败';
      job.error = '请先在设置中填写服务器地址';
      await _save();
      notifyListeners();
      return;
    }
    final file = File(job.path);
    if (job.libraryId == 0 && !await file.exists()) {
      job.status = '失败';
      job.error = '源文件已不存在，请重新导入';
      await _save();
      notifyListeners();
      return;
    }
    final client = ApiClient(serverBase, accountToken.isNotEmpty ? accountToken : apiToken);
    try {
      final health = await client.health();
      if (health['processing_ready'] == false) {
        final runtime = health['runtime'];
        final issues = runtime is Map && runtime['issues'] is List
            ? (runtime['issues'] as List).join('；')
            : '服务器 AI 分轨运行环境未安装完整';
        throw FormatException(issues);
      }
      job.status = job.libraryId > 0 ? '加载中' : '上传中';
      job.stage = job.libraryId > 0 ? '连接服务器歌曲库' : '上传音频';
      job.progress = job.libraryId > 0 ? .01 : .03;
      job.error = '';
      await _save();
      notifyListeners();

      Map<String, dynamic> response;
      if (job.libraryId > 0) {
        job.stage = '定位服务器歌曲';
        job.progress = .04;
        await _save();
        notifyListeners();
        job.stage = '提交 AI 处理任务';
        job.progress = .06;
        await _save();
        notifyListeners();
        response = await client.processLibrary(job);
      } else {
        response = await client.submit(job);
      }
      job.serverJobId = '${response['job_id'] ?? response['id'] ?? ''}';
      if (job.serverJobId.isEmpty) throw const FormatException('服务器没有返回 job_id');
      job.status = '处理中';
      job.stage = '服务器已接收';
      job.progress = .08;
      await _save();
      notifyListeners();
      await _pollJob(client, job);
    } catch (error) {
      job.status = '失败';
      job.error = _friendlyJobError(error);
      await _save();
      notifyListeners();
    }
  }

  Future<void> resumeJob(PipelineJob job) async {
    // A failed server job is immutable. Re-polling the same id only returns the
    // same error forever, even after the server/model environment is repaired.
    // Start a fresh server job while keeping the user's pipeline card.
    if (job.status == '失败') {
      job.serverJobId = '';
      job.progress = 0;
      job.stage = '重新提交任务';
      job.error = '';
      await _save();
      notifyListeners();
      await startJob(job);
      return;
    }
    if (job.serverJobId.isEmpty) {
      await startJob(job);
      return;
    }
    job.status = '处理中';
    job.error = '';
    notifyListeners();
    try {
      await _pollJob(ApiClient(serverBase, accountToken.isNotEmpty ? accountToken : apiToken), job);
    } catch (error) {
      job.status = '失败';
      job.error = _friendlyJobError(error);
      await _save();
      notifyListeners();
    }
  }

  Future<void> _pollJob(ApiClient client, PipelineJob job) async {
    while (job.status == '处理中') {
      final result = await client.job(job.serverJobId);
      final rawStatus = '${result['status'] ?? 'processing'}'.toLowerCase();
      job.stage = '${result['stage'] ?? result['message'] ?? job.stage}';
      final rawProgress = (result['progress'] as num?)?.toDouble() ?? job.progress;
      job.progress = (rawProgress > 1 ? rawProgress / 100 : rawProgress).clamp(0, 1).toDouble();
      job.originalKey = '${result['key'] ?? result['original_key'] ?? job.originalKey}';
      final rawArtifacts = result['artifacts'];
      if (rawArtifacts is Map) {
        job.artifacts = rawArtifacts.map((key, value) => MapEntry('$key', '$value'));
      }
      if (<String>{'completed', 'complete', 'done', 'success', 'succeeded'}.contains(rawStatus)) {
        job.status = '完成';
        job.stage = '全部完成';
        job.progress = 1;
      } else if (<String>{'failed', 'error', 'cancelled', 'canceled'}.contains(rawStatus)) {
        job.status = '失败';
        job.error = _friendlyJobError(result['error'] ?? result['message'] ?? '服务器任务失败');
      }
      await _save();
      notifyListeners();
      if (job.status != '处理中') break;
      await Future<void>.delayed(const Duration(seconds: 2));
    }
  }

  String _friendlyJobError(Object error) {
    var message = '$error'
        .replaceFirst(RegExp(r'^(FormatException|HttpException|Exception):\s*'), '')
        .trim();
    final lower = message.toLowerCase();
    if (lower.contains("no module named 'torch'") || lower.contains('缺少 torch')) {
      return '服务器未安装 AI 分轨运行环境（缺少 PyTorch）：请安装 requirements-server.txt 后重启服务。';
    }
    if (lower.contains("no module named 'demucs'") || lower.contains('缺少 demucs')) {
      return '服务器未安装 AI 分轨运行环境（缺少 Demucs）：请安装 requirements-server.txt 后重启服务。';
    }
    if (lower.contains('audio_separator') || lower.contains('audio-separator')) {
      return '服务器未安装 UVR 分轨运行环境（audio-separator）：请重新运行 Install-AI-Engine.bat 后重启服务。';
    }
    if (lower.contains('ffmpeg') && (lower.contains('not found') || lower.contains('未找到'))) {
      return '服务器缺少 FFmpeg，暂时不能读取或处理歌曲。';
    }
    if (lower.contains('origin web server') || lower.contains('cloudflare')) {
      return 'AI 服务器暂时没有完整响应，请确认服务端和 Cloudflare Tunnel 均在线后重试。';
    }
    if (lower.contains('http 404') || lower.contains('"detail":"not found"')) {
      return 'AI 任务接口未连接到新版服务器，请检查 Cloudflare 曲库路由后重试。';
    }
    return message.isEmpty ? 'AI 处理失败，请稍后重试' : message;
  }

  Future<void> setTranspose(PipelineJob job, int value) async {
    job.semitones = value.clamp(-12, 12).toInt();
    await _save();
    notifyListeners();
  }

  Future<void> setArrangementMode(PipelineJob job, String value) async {
    job.arrangementMode = value;
    await _save();
    notifyListeners();
  }

  Future<void> authenticate({required String account, required String phoneValue, required String password, required bool register, String nicknameValue = '', String code = ''}) async {
    if (serverBase.isEmpty) throw const FormatException('请先配置 AI 服务器地址');
    accountState = register ? '注册中' : '登录中';
    notifyListeners();
    try {
      final result = await ApiClient(serverBase, apiToken).postJson(
        register ? '/api/v1/library/mobile/auth/register' : '/api/v1/library/mobile/auth/login',
        {
          'username': account.trim(),
          'phone': phoneValue.trim(),
          'password': password,
          'nickname': nicknameValue.trim(),
          'code': code.trim(),
        },
      );
      accountToken = '${result['token'] ?? ''}';
      if (accountToken.isEmpty) throw const FormatException('服务器没有返回登录令牌');
      username = '${result['username'] ?? account.trim()}';
      nickname = '${result['nickname'] ?? username}';
      phone = '${result['phone'] ?? phoneValue.trim()}';
      guestMode = false;
      accountState = '已登录';
      await _save();
      await refreshProfile();
      await refreshCommunity();
    } catch (_) {
      accountState = '登录失败';
      notifyListeners();
      rethrow;
    }
  }

  Future<void> sendSmsCode(String phoneValue, String purpose) async {
    await ApiClient(serverBase, apiToken).postJson('/api/v1/library/mobile/auth/sms/send', {
      'phone': phoneValue.trim(),
      'purpose': purpose,
    });
  }

  Future<void> resetPassword(String phoneValue, String code, String newPassword) async {
    await ApiClient(serverBase, apiToken).postJson('/api/v1/library/mobile/auth/password/reset', {
      'phone': phoneValue.trim(),
      'code': code.trim(),
      'new_password': newPassword,
    });
  }

  Future<void> refreshProfile() async {
    if (accountToken.isEmpty) return;
    try {
      final result = await ApiClient(serverBase, accountToken).getJson('/api/v1/library/mobile/account/me');
      username = '${result['username'] ?? username}';
      nickname = '${result['nickname'] ?? nickname}';
      phone = '${result['phone'] ?? ''}';
      avatarUrl = '${result['avatar_url'] ?? ''}';
      gender = '${result['gender'] ?? '保密'}';
      bio = '${result['bio'] ?? ''}';
      origin = '${result['origin'] ?? ''}';
      address = '${result['address'] ?? ''}';
      wechat = '${result['wechat'] ?? ''}';
      accountState = '已登录';
      await _save();
      notifyListeners();
    } catch (error) {
      if ('$error'.contains('请先登录') || '$error'.contains('访问令牌')) await logout();
    }
  }

  Future<void> updateProfile(Map<String, dynamic> payload) async {
    final result = await ApiClient(serverBase, accountToken).putJson('/api/v1/library/mobile/account/me', payload);
    nickname = '${result['nickname'] ?? nickname}';
    avatarUrl = '${result['avatar_url'] ?? ''}';
    gender = '${result['gender'] ?? '保密'}';
    bio = '${result['bio'] ?? ''}';
    origin = '${result['origin'] ?? ''}';
    address = '${result['address'] ?? ''}';
    wechat = '${result['wechat'] ?? ''}';
    await _save();
    notifyListeners();
  }

  Future<void> logout() async {
    accountToken = '';
    username = '';
    nickname = '';
    phone = '';
    avatarUrl = '';
    gender = '保密';
    bio = '';
    origin = '';
    address = '';
    wechat = '';
    accountState = '未登录';
    guestMode = false;
    communityMessages.clear();
    await _save();
    notifyListeners();
  }

  Future<void> enterGuestTesting() async {
    guestMode = true;
    accountState = '测试模式';
    await _save();
    notifyListeners();
    unawaited(testServer());
    unawaited(refreshCatalog(silent: true));
  }

  Future<void> refreshCommunity() async {
    if (accountToken.isEmpty || serverBase.isEmpty) return;
    final result = await ApiClient(serverBase, accountToken).getJson('/api/v1/library/mobile/community/messages?limit=100');
    final rows = result['messages'];
    communityMessages
      ..clear()
      ..addAll(rows is List
          ? rows.map((row) => CommunityMessage.fromJson(Map<String, dynamic>.from(row as Map)))
          : const <CommunityMessage>[]);
    notifyListeners();
  }

  Future<void> sendCommunity(String content) async {
    final value = content.trim();
    if (value.isEmpty) return;
    if (accountToken.isEmpty) throw const FormatException('请先登录账号');
    await ApiClient(serverBase, accountToken).postJson('/api/v1/library/mobile/community/messages', {'content': value});
    await refreshCommunity();
  }
}

class ApiClient {
  ApiClient(this.base, this.token);
  final String base;
  final String token;

  Future<Map<String, dynamic>> health() async {
    Object? lastError;
    for (final path in const ['/api/v1/library/mobile/health', '/api/v1/library/health', '/health', '/api/health']) {
      try {
        return await _jsonRequest('GET', path);
      } catch (error) {
        lastError = error;
      }
    }
    throw Exception(lastError ?? '健康检查失败');
  }

  Future<Map<String, dynamic>> submit(PipelineJob job) async {
    Object? lastError;
    for (final path in const ['/api/v1/library/mobile/jobs', '/api/v1/library/jobs', '/api/v1/jobs']) {
      try {
        return await _submitToPath(job, path);
      } catch (error) {
        lastError = error;
        if (!_isRouteMissing(error)) rethrow;
      }
    }
    throw FormatException('$lastError');
  }

  Future<Map<String, dynamic>> _submitToPath(PipelineJob job, String path) async {
    final uri = Uri.parse('$base$path');
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 15);
    try {
      final request = await client.postUrl(uri);
      _headers(request);
      final boundary = 'juweier-${DateTime.now().microsecondsSinceEpoch}';
      request.headers.contentType = ContentType('multipart', 'form-data', parameters: {'boundary': boundary});

      void field(String name, String value) {
        request.write('--$boundary\r\n');
        request.write('Content-Disposition: form-data; name="$name"\r\n\r\n$value\r\n');
      }

      field('arrangement_mode', 'live_band');
      field('transpose', '${job.semitones}');
      field('output', 'wav_mp3');
      field('original_filename', job.fileName);
      request.write('--$boundary\r\n');
      request.write('Content-Disposition: form-data; name="file"; filename="${_asciiUploadName(job.fileName)}"\r\n');
      request.write('Content-Type: application/octet-stream\r\n\r\n');
      await request.addStream(File(job.path).openRead());
      request.write('\r\n--$boundary--\r\n');
      final response = await request.close().timeout(const Duration(minutes: 10));
      return await _decode(response);
    } finally {
      client.close(force: true);
    }
  }

  Future<Map<String, dynamic>> job(String id) => _jsonRequestAny('GET', [
        '/api/v1/library/mobile/jobs/$id',
        '/api/v1/library/jobs/$id',
        '/api/v1/jobs/$id',
      ]);

  Future<Map<String, dynamic>> library(String query, String category, {int since = 0, String initial = '全部'}) {
    final params = 'q=${Uri.encodeQueryComponent(query)}&category=${Uri.encodeQueryComponent(category)}&initial=${Uri.encodeQueryComponent(initial)}&since=$since';
    return _jsonRequestAny('GET', [
      '/api/v1/library/mobile/catalog?$params',
      '/api/v1/library/catalog?$params',
      '/api/v1/library?$params',
    ]);
  }

  Future<Map<String, dynamic>> processLibrary(PipelineJob job) => _jsonRequestAny('POST', [
        '/api/v1/library/mobile/catalog/${job.libraryId}/process',
        '/api/v1/library/${job.libraryId}/process',
      ], payload: {'arrangement_mode': 'live_band', 'transpose': job.semitones, 'output': 'wav_mp3'});

  Future<Map<String, dynamic>> importLink(String url) => _jsonRequestAny('POST', [
        '/api/v1/library/mobile/import-url',
        '/api/v1/library/import-url',
      ], payload: {'url': url});

  Future<Map<String, dynamic>> generateLyrics(Map<String, dynamic> payload) =>
      postJson('/api/v1/library/mobile/lyrics/generate', payload);

  Future<Map<String, dynamic>> submitFeedback(Map<String, dynamic> payload) =>
      postJson('/api/v1/library/mobile/feedback', payload);

  Future<Map<String, dynamic>> getJson(String path) => _jsonRequest('GET', path);

  Future<Map<String, dynamic>> postJson(String path, Map<String, dynamic> payload) =>
      _jsonRequest('POST', path, payload: payload);

  Future<Map<String, dynamic>> putJson(String path, Map<String, dynamic> payload) =>
      _jsonRequest('PUT', path, payload: payload);

  Future<Map<String, dynamic>> _jsonRequestAny(String method, List<String> paths, {Map<String, dynamic>? payload}) async {
    Object? lastError;
    for (final path in paths) {
      try {
        return await _jsonRequest(method, path, payload: payload);
      } catch (error) {
        lastError = error;
        if (!_isRouteMissing(error)) rethrow;
      }
    }
    throw FormatException('$lastError');
  }

  Future<Map<String, dynamic>> _jsonRequest(String method, String path, {Map<String, dynamic>? payload}) async {
    Object? lastError;
    for (var attempt = 0; attempt < 3; attempt++) {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 12);
      try {
        final request = await client.openUrl(method, Uri.parse('$base$path'));
        _headers(request);
        if (payload != null) {
          request.headers.contentType = ContentType.json;
          request.write(jsonEncode(payload));
        }
        final response = await request.close().timeout(const Duration(seconds: 25));
        if (<int>{502, 503, 504}.contains(response.statusCode) && attempt < 2) {
          await response.drain<void>();
          await Future<void>.delayed(Duration(milliseconds: 600 * (attempt + 1)));
          continue;
        }
        return await _decode(response);
      } catch (error) {
        lastError = error;
        if (_isRouteMissing(error) || attempt >= 2) rethrow;
        await Future<void>.delayed(Duration(milliseconds: 600 * (attempt + 1)));
      } finally {
        client.close(force: true);
      }
    }
    throw FormatException('$lastError');
  }

  void _headers(HttpClientRequest request) {
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    request.headers.set(HttpHeaders.userAgentHeader, 'Juweier-Music/$appVersion');
    if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
  }

  Future<Map<String, dynamic>> _decode(HttpClientResponse response) async {
    final body = await response.transform(utf8.decoder).join();
    if (response.statusCode < 200 || response.statusCode >= 300) {
      var message = '服务器请求失败（${response.statusCode}）';
      try {
        final decoded = jsonDecode(body);
        if (decoded is Map && decoded['detail'] != null) message = '${decoded['detail']}';
      } catch (_) {
        if (body.trim().isNotEmpty) message = body.length > 240 ? body.substring(0, 240) : body;
      }
      throw FormatException(message);
    }
    if (body.trim().isEmpty) return <String, dynamic>{};
    try {
      final decoded = jsonDecode(body);
      if (decoded is! Map) throw const FormatException('返回内容不是 JSON 对象');
      return Map<String, dynamic>.from(decoded);
    } catch (_) {
      final contentType = response.headers.contentType?.mimeType ?? '未知类型';
      if (body.toLowerCase().contains('cloudflare') || body.trimLeft().startsWith('<')) {
        throw FormatException('AI 服务器返回了网页而不是数据（$contentType），请检查 Cloudflare Tunnel 与 Mobile API 路由。');
      }
      throw FormatException('AI 服务器返回的数据格式不完整（$contentType），请稍后重试。');
    }
  }

  bool _isRouteMissing(Object error) {
    final text = '$error'.toLowerCase();
    return text.contains('not found') || text.contains('（404）') || text.contains('(404)');
  }

  String _asciiUploadName(String value) {
    final normalized = value.replaceAll('\\', '/').split('/').last;
    final dot = normalized.lastIndexOf('.');
    var extension = dot >= 0 ? normalized.substring(dot).toLowerCase() : '.mp3';
    if (!RegExp(r'^\.[a-z0-9]{1,8}$').hasMatch(extension)) extension = '.mp3';
    final digest = utf8.encode(normalized).fold<int>(0, (hash, byte) => ((hash * 31) + byte) & 0x7fffffff);
    return 'upload_${digest.toRadixString(16)}$extension';
  }
}

class JuweierMusicApp extends StatelessWidget {
  const JuweierMusicApp({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: store,
    builder: (context, _) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: appName,
        theme: ThemeData(
          useMaterial3: true,
          brightness: Brightness.dark,
          colorScheme: ColorScheme.fromSeed(
            seedColor: accent,
            brightness: Brightness.dark,
            primary: accent,
            secondary: violet,
            surface: const Color(0xFF1B121F),
          ),
          scaffoldBackgroundColor: const Color(0xFF100A14),
          cardTheme: CardThemeData(
            color: const Color(0xFF1B121F),
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(20),
              side: const BorderSide(color: Color(0xFF432B39)),
            ),
          ),
          inputDecorationTheme: InputDecorationTheme(
            filled: true,
            fillColor: const Color(0xFF160E1B),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
          ),
        ),
        home: store.accountToken.isEmpty && !store.guestMode ? AuthGatePage(store: store) : MainShell(store: store),
      ),
  );
}

class AuthGatePage extends StatefulWidget {
  const AuthGatePage({super.key, required this.store});
  final AppStore store;

  @override
  State<AuthGatePage> createState() => _AuthGatePageState();
}

class _AuthGatePageState extends State<AuthGatePage> {
  final account = TextEditingController();
  final phone = TextEditingController();
  final nickname = TextEditingController();
  final password = TextEditingController();
  final code = TextEditingController();
  String mode = '登录';
  bool busy = false;
  int countdown = 0;
  Timer? timer;

  @override
  void dispose() {
    timer?.cancel();
    account.dispose(); phone.dispose(); nickname.dispose(); password.dispose(); code.dispose();
    super.dispose();
  }

  Future<void> sendCode() async {
    if (phone.text.trim().isEmpty || countdown > 0) return;
    setState(() => busy = true);
    try {
      await widget.store.sendSmsCode(phone.text, mode == '找回密码' ? 'reset' : 'register');
      if (!mounted) return;
      setState(() => countdown = 60);
      timer?.cancel();
      timer = Timer.periodic(const Duration(seconds: 1), (value) {
        if (!mounted || countdown <= 1) {
          value.cancel();
          if (mounted) setState(() => countdown = 0);
        } else {
          setState(() => countdown--);
        }
      });
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('验证码已发送，5 分钟内有效')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> submit() async {
    setState(() => busy = true);
    try {
      if (mode == '找回密码') {
        await widget.store.resetPassword(phone.text, code.text, password.text);
        if (!mounted) return;
        setState(() { mode = '登录'; code.clear(); password.clear(); });
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('密码已重置，请使用手机号或账号登录')));
      } else {
        await widget.store.authenticate(
          account: account.text,
          phoneValue: phone.text,
          password: password.text,
          register: mode == '注册',
          nicknameValue: nickname.text,
          code: code.text,
        );
      }
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final register = mode == '注册';
    final reset = mode == '找回密码';
    return Scaffold(body: SafeArea(child: Center(child: SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 520), child: Card(
        child: Padding(padding: const EdgeInsets.all(24), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Container(width: 64, height: 64, padding: const EdgeInsets.all(6), decoration: BoxDecoration(color: const Color(0xFF2C1024), borderRadius: BorderRadius.circular(18)), child: Image.asset('assets/juweier_brand_mark_v322.png')),
            const SizedBox(width: 14),
            const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(appName, style: TextStyle(fontSize: 28, fontWeight: FontWeight.w900)), Text('登录后使用音乐库、AI 处理和内测群聊')])),
          ]),
          const SizedBox(height: 22),
          SegmentedButton<String>(
            segments: const [ButtonSegment(value: '登录', label: Text('登录')), ButtonSegment(value: '注册', label: Text('注册')), ButtonSegment(value: '找回密码', label: Text('找回密码'))],
            selected: {mode}, onSelectionChanged: (value) => setState(() => mode = value.first),
          ),
          const SizedBox(height: 18),
          if (!reset) TextField(controller: account, decoration: InputDecoration(labelText: register ? '自选账号（可留空，使用手机号注册）' : '账号或手机号')),
          if (!reset) const SizedBox(height: 10),
          if (register || reset) ...[
            TextField(controller: phone, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: '手机号', prefixText: '+86 ')),
            const SizedBox(height: 10),
            Row(children: [
              Expanded(child: TextField(controller: code, keyboardType: TextInputType.number, maxLength: 6, decoration: const InputDecoration(labelText: '短信验证码', counterText: ''))),
              const SizedBox(width: 10),
              OutlinedButton(onPressed: busy || countdown > 0 ? null : sendCode, child: Text(countdown > 0 ? '${countdown}秒' : '获取验证码')),
            ]),
            const SizedBox(height: 10),
          ],
          if (register) ...[
            TextField(controller: nickname, decoration: const InputDecoration(labelText: '昵称（可选）')),
            const SizedBox(height: 10),
          ],
          TextField(controller: password, obscureText: true, decoration: InputDecoration(labelText: reset ? '设置新密码（至少 6 位）' : '密码（至少 6 位）')),
          const SizedBox(height: 18),
          FilledButton.icon(onPressed: busy ? null : submit, icon: busy ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.login), label: Text(reset ? '重置密码' : register ? '注册并进入' : '登录')),
          if (!register && !reset) ...[
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: busy ? null : widget.store.enterGuestTesting,
              icon: const Icon(Icons.science_outlined),
              label: const Text('先进入测试（无需验证码）'),
            ),
            const SizedBox(height: 6),
            const Text('测试模式可体验曲库、导入、AI 流水线和谱面；账号资料与内测群聊仍需正式登录。', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFFBDAAB5), fontSize: 12)),
          ],
          const SizedBox(height: 12),
          const Text('验证码 60 秒内只能发送 1 次，5 分钟内有效。注册即表示同意用户协议与隐私政策。', style: TextStyle(color: Color(0xFFBDAAB5), fontSize: 12)),
        ])),
      )),
    ))));
  }
}

class MainShell extends StatefulWidget {
  const MainShell({super.key, required this.store});
  final AppStore store;

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int index = 0;

  Future<void> pickAudio() async {
    final files = await FilePicker.pickFiles(type: FileType.audio);
    if (files.isEmpty || !mounted) return;
    final report = await widget.store.addFiles(files);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('已导入 ${report.added} 首${report.skipped > 0 ? '，跳过重复/无路径 ${report.skipped} 首' : ''}')),
    );
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: widget.store,
        builder: (context, _) {
          final pages = [
            DashboardPage(store: widget.store, onImport: pickAudio, onNavigate: (i) => setState(() => index = i)),
            LibraryPage(store: widget.store, onImport: pickAudio, onOpenPipeline: () => setState(() => index = 2)),
            PipelinePage(store: widget.store),
            PerformancePage(store: widget.store),
            CommunityPage(store: widget.store),
          ];
          return Scaffold(
            body: SafeArea(child: pages[index]),
            bottomNavigationBar: NavigationBar(
              selectedIndex: index,
              onDestinationSelected: (value) => setState(() => index = value),
              destinations: const [
                NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: '首页'),
                NavigationDestination(icon: Icon(Icons.library_music_outlined), selectedIcon: Icon(Icons.library_music), label: '音乐库'),
                NavigationDestination(icon: Icon(Icons.auto_awesome_outlined), selectedIcon: Icon(Icons.auto_awesome), label: '流水线'),
                NavigationDestination(icon: Icon(Icons.piano_outlined), selectedIcon: Icon(Icons.piano), label: '演出'),
                NavigationDestination(icon: Icon(Icons.forum_outlined), selectedIcon: Icon(Icons.forum), label: '内测群'),
              ],
            ),
          );
        },
      );
}

class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key, required this.store, required this.onImport, required this.onNavigate});
  final AppStore store;
  final VoidCallback onImport;
  final ValueChanged<int> onNavigate;

  @override
  Widget build(BuildContext context) {
    final running = store.jobs.where((e) => e.isRunning).length;
    final done = store.jobs.where((e) => e.isDone).length;
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 30),
      children: [
        Row(children: [
          Container(
            width: 72, height: 72, padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              gradient: const LinearGradient(colors: [Color(0xFF2C1024), Color(0xFF160D25)]),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: const Color(0xFFFF8A2A).withValues(alpha: .45)),
              boxShadow: const [BoxShadow(color: Color(0x44FF6A00), blurRadius: 20)],
            ),
            child: Image.asset('assets/juweier_brand_mark_v322.png', fit: BoxFit.contain),
          ),
          const SizedBox(width: 14),
          const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(appName, style: TextStyle(fontSize: 28, fontWeight: FontWeight.w900)),
            Text('AI 分轨 · 智能改编 · 乐手谱面', style: TextStyle(color: Color(0xFFBDAAB5))),
          ])),
          IconButton.filledTonal(
            tooltip: '个人资料', icon: const Icon(Icons.person),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProfilePage(store: store))),
          ),
        ]),
        const SizedBox(height: 18),
        ServerCard(store: store),
        const SizedBox(height: 12),
        Card(child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('开始制作', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            const Text('一次可导入多首，重复文件会自动跳过。', style: TextStyle(color: Color(0xFFBDAAB5))),
            const SizedBox(height: 14),
            FilledButton.icon(onPressed: onImport, icon: const Icon(Icons.add_to_photos), label: const Text('导入本地音乐')),
            const SizedBox(height: 8),
            OutlinedButton.icon(onPressed: () => onNavigate(2), icon: const Icon(Icons.play_arrow), label: const Text('进入自动流水线')),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => LyricsStudioPage(store: store))),
              icon: const Icon(Icons.lyrics_outlined),
              label: const Text('AI 歌词创作（普通话 / 粤语 / 英语）'),
            ),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(child: OutlinedButton.icon(onPressed: () => onNavigate(4), icon: const Icon(Icons.forum), label: const Text('内测群聊'))),
              const SizedBox(width: 8),
              Expanded(child: OutlinedButton.icon(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => Scaffold(body: SafeArea(child: SettingsPage(store: store))))),
                icon: const Icon(Icons.settings),
                label: const Text('设置'),
              )),
            ]),
          ]),
        )),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: MetricCard(label: '音乐', value: '${store.jobs.length}', icon: Icons.library_music)),
          const SizedBox(width: 10),
          Expanded(child: MetricCard(label: '处理中', value: '$running', icon: Icons.graphic_eq)),
          const SizedBox(width: 10),
          Expanded(child: MetricCard(label: '已完成', value: '$done', icon: Icons.task_alt)),
        ]),
        const SizedBox(height: 14),
        const Text('核心能力', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
        const SizedBox(height: 10),
        const Wrap(spacing: 10, runSpacing: 10, children: [
          FeatureChip(icon: Icons.multitrack_audio, text: 'AI 六轨+电吉他'),
          FeatureChip(icon: Icons.music_note, text: '自动和弦与段落'),
          FeatureChip(icon: Icons.queue_music, text: '五线谱 / 六线谱'),
          FeatureChip(icon: Icons.tune, text: '升降调与 Capo'),
          FeatureChip(icon: Icons.piano, text: '乐队智能改编'),
          FeatureChip(icon: Icons.live_tv, text: '现场演出模式'),
          FeatureChip(icon: Icons.queue_music, text: 'Setlist 演出歌单'),
          FeatureChip(icon: Icons.forum, text: '账号与内测群聊'),
          FeatureChip(icon: Icons.lyrics, text: 'AI 歌词初稿'),
        ]),
      ],
    );
  }
}

class LibraryPage extends StatefulWidget {
  const LibraryPage({super.key, required this.store, required this.onImport, required this.onOpenPipeline});
  final AppStore store;
  final VoidCallback onImport;
  final VoidCallback onOpenPipeline;

  @override
  State<LibraryPage> createState() => _LibraryPageState();
}

class _LibraryPageState extends State<LibraryPage> {
  final search = TextEditingController();
  final previewPlayer = AudioPlayer();
  String category = '全部';
  String initial = '全部';
  String discoveryTab = '乐库';
  bool loading = false;

  @override
  void initState() {
    super.initState();
    unawaited(refresh());
  }

  @override
  void dispose() {
    search.dispose();
    unawaited(previewPlayer.dispose());
    super.dispose();
  }

  Future<void> playSong(LibrarySong song) async {
    if (song.audioUrl.isEmpty) return;
    try {
      final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;
      await previewPlayer.setUrl(
        song.audioUrl,
        headers: token.isEmpty ? null : {'Authorization': 'Bearer $token'},
      );
      await previewPlayer.play();
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('歌曲播放失败：$error')));
    }
  }

  Future<void> refresh() async {
    if (widget.store.serverBase.isEmpty) return;
    setState(() => loading = true);
    try {
      await widget.store.refreshCatalog(query: search.text, category: category);
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('歌曲库读取失败：$error')));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> importLink() async {
    final controller = TextEditingController();
    final url = await showDialog<String>(context: context, builder: (context) => AlertDialog(
      title: const Text('导入本人有权使用的链接'),
      content: TextField(
        controller: controller,
        minLines: 2,
        maxLines: 5,
        decoration: const InputDecoration(
          hintText: '粘贴本人有权使用的公开音频直链',
          helperText: '本软件目前仅供学习与研究使用，不提供歌曲下载服务。',
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(onPressed: () => Navigator.pop(context, controller.text.trim()), child: const Text('导入授权音频')),
      ],
    ));
    controller.dispose();
    if (url == null || url.isEmpty) return;
    setState(() => loading = true);
    try {
      await widget.store.importPublicLink(url);
      if (!mounted) return;
      setState(() => category = '临时歌曲库');
      await refresh();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('歌曲已导入服务器临时歌曲库')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('链接导入失败：$error')));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  String artistInitial(LibrarySong song) {
    final value = song.artistInitial.trim().toUpperCase();
    return RegExp(r'^[A-Z]$').hasMatch(value) ? value : '#';
  }

  ImageProvider<Object>? artistImage(LibrarySong song) {
    if (song.coverUrl.isEmpty) return null;
    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;
    return NetworkImage(song.coverUrl, headers: token.isEmpty ? null : {'Authorization': 'Bearer $token'});
  }

  Future<void> processSong(LibrarySong song) async {
    if (song.isAiReady) {
      final job = await widget.store.addLibrarySong(song);
      job.status = '完成';
      job.stage = '服务器成果可用';
      job.progress = 1;
      job.artifacts
        ..clear()
        ..addAll(song.artifacts);
      await widget.store._save();
      widget.store.notifyListeners();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: const Text('已打开服务器预处理成果：分轨、歌词和乐谱可直接使用'),
        action: SnackBarAction(label: '查看', onPressed: widget.onOpenPipeline),
      ));
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('这首歌曲正在等待服务器管理员预处理，完成后会自动显示歌词、乐谱和独立乐器轨。'),
    ));
  }

  void openArtist(MapEntry<String, List<LibrarySong>> group) {
    showModalBottomSheet<void>(
      context: context, isScrollControlled: true, showDragHandle: true,
      builder: (context) => DraggableScrollableSheet(
        expand: false, initialChildSize: .78, maxChildSize: .95, minChildSize: .45,
        builder: (context, controller) => Column(children: [
          Padding(padding: const EdgeInsets.fromLTRB(20, 4, 20, 14), child: Row(children: [
            CircleAvatar(radius: 34, backgroundColor: const Color(0xFF432B39), foregroundImage: artistImage(group.value.first), child: Text(group.key.substring(0, 1), style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900))),
            const SizedBox(width: 14),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(group.key, style: const TextStyle(fontSize: 23, fontWeight: FontWeight.w900)), Text('${group.value.length} 首服务器歌曲', style: const TextStyle(color: Color(0xFFBDAAB5)))])),
          ])),
          Expanded(child: ListView.builder(controller: controller, itemCount: group.value.length, itemBuilder: (context, index) {
            final song = group.value[index];
            return ListTile(
              leading: CircleAvatar(backgroundColor: accent.withValues(alpha: .16), child: Text('${index + 1}')),
              title: Text(song.title), subtitle: Text('${song.language} · ${song.genre} · ${song.processingStatus}'),
              onTap: () => unawaited(playSong(song)),
              trailing: FilledButton.tonal(onPressed: () { Navigator.pop(context); unawaited(processSong(song)); }, child: Text(song.isAiReady ? '打开成果' : '处理中')),
            );
          })),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final filterText = search.text.trim().toLowerCase();
    final visibleSongs = widget.store.catalog.where((song) {
      final categoryMatches = category == '全部' || category == '推荐' || song.category == category || song.language == category || song.genre == category || song.tags.contains(category) || (category == 'AI已完成' && song.isAiReady) || (category == '有歌词' && song.lyricsUrl.isNotEmpty) || (category == '有乐谱' && song.artifacts.containsKey('score_data')) || (category == '有分轨' && song.artifacts.containsKey('stem_vocals'));
      final textMatches = filterText.isEmpty ||
          song.title.toLowerCase().contains(filterText) ||
          song.artist.toLowerCase().contains(filterText) ||
          song.album.toLowerCase().contains(filterText);
      return categoryMatches && textMatches;
    });
    final grouped = <String, List<LibrarySong>>{};
    for (final song in visibleSongs) {
      grouped.putIfAbsent(song.artist, () => <LibrarySong>[]).add(song);
    }
    final artists = grouped.entries.where((entry) => initial == '全部' || artistInitial(entry.value.first) == initial).toList()
      ..sort((a, b) => a.key.toLowerCase().compareTo(b.key.toLowerCase()));
    final featured = grouped.entries.take(8).toList();
    final songs = visibleSongs.where((song) => initial == '全部' || artistInitial(song) == initial).toList();
    return Column(children: [
        PageHeader(title: '橘味儿乐库', subtitle: '${widget.store.catalog.length} 首已发布歌曲 · 打开即播、成果即用', action: IconButton(onPressed: refresh, icon: const Icon(Icons.sync))),
        SizedBox(height: 48, child: ListView(
          padding: const EdgeInsets.symmetric(horizontal: 16), scrollDirection: Axis.horizontal,
          children: [for (final value in const ['推荐','乐库','歌单','歌手','分类','AI成果'])
            Padding(padding: const EdgeInsets.only(right: 8), child: ChoiceChip(
              label: Text(value), selected: discoveryTab == value,
              onSelected: (_) => setState(() {
                discoveryTab = value;
                category = value == 'AI成果' ? 'AI已完成' : value == '推荐' ? '推荐' : '全部';
              }),
            )),
          ],
        )),
        if (discoveryTab == '推荐') Container(
          margin: const EdgeInsets.fromLTRB(16, 0, 16, 10), padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            gradient: const LinearGradient(colors: [Color(0xFF5B2945), Color(0xFFFF7A18)]),
            borderRadius: BorderRadius.circular(20),
          ),
          child: const Row(children: [Icon(Icons.auto_awesome, size: 38), SizedBox(width: 14), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('服务器 AI 精选', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)), Text('歌词、五线谱、六线谱与独立乐器轨预先生成')]))]),
        ),
        Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 8), child: Column(children: [
          Row(children: [
          Expanded(child: TextField(
            controller: search,
            textInputAction: TextInputAction.search,
            onChanged: (_) => setState(() {}),
            onSubmitted: (_) => setState(() {}),
            decoration: const InputDecoration(hintText: '搜索歌手、歌曲或专辑', prefixIcon: Icon(Icons.search)),
          )),
          const SizedBox(width: 8),
          FilledButton.icon(onPressed: () => setState(() {}), icon: const Icon(Icons.search), label: const Text('搜索')),
          ]),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            SizedBox(width: 190, child: DropdownButtonFormField<String>(initialValue: widget.store.catalogCategories.contains(category) ? category : '全部', decoration: const InputDecoration(labelText: '歌曲分类'), items: widget.store.catalogCategories.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(), onChanged: (value) { if (value != null) setState(() => category = value); })),
            OutlinedButton.icon(onPressed: widget.onImport, icon: const Icon(Icons.audio_file), label: const Text('本地导入')),
            OutlinedButton.icon(onPressed: importLink, icon: const Icon(Icons.link), label: const Text('链接导入')),
          ]),
        ])),
        if (loading) const LinearProgressIndicator(minHeight: 2),
        if (widget.store.catalog.isNotEmpty) ...[
          SizedBox(height: 116, child: ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 10), scrollDirection: Axis.horizontal,
            itemCount: featured.length, separatorBuilder: (_, __) => const SizedBox(width: 14),
            itemBuilder: (context, index) {
              final group = featured[index];
              return InkWell(onTap: () => openArtist(group), borderRadius: BorderRadius.circular(44), child: SizedBox(width: 76, child: Column(children: [
                CircleAvatar(radius: 32, backgroundColor: const Color(0xFF432B39), foregroundImage: artistImage(group.value.first), child: Text(group.key.substring(0, 1), style: const TextStyle(fontWeight: FontWeight.w900))),
                const SizedBox(height: 6),
                Text(group.key, maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.center),
              ])));
            },
          )),
          SizedBox(height: 52, child: ListView(
            padding: const EdgeInsets.symmetric(horizontal: 16), scrollDirection: Axis.horizontal,
            children: [for (final value in const ['全部','A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T','U','V','W','X','Y','Z','#'])
              Padding(padding: const EdgeInsets.only(right: 7), child: ChoiceChip(label: Text(value), selected: initial == value, onSelected: (_) => setState(() => initial = value))),
            ],
          )),
        ],
        Expanded(
          child: widget.store.catalog.isEmpty
              ? EmptyState(icon: Icons.library_music, title: '暂时没有已发布歌曲', detail: 'App 不会扫描手机或电脑硬盘。服务器管理员发布曲库后会自动同步；离线时仍保留上次歌曲索引。', action: refresh)
              : discoveryTab == '歌手' ? ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  itemCount: artists.length,
                  itemBuilder: (context, i) {
                    final group = artists[i];
                    return Card(child: ListTile(
                      onTap: () => openArtist(group),
                      leading: CircleAvatar(radius: 26, backgroundColor: const Color(0xFF432B39), foregroundImage: artistImage(group.value.first), child: Text(group.key.substring(0, 1), style: const TextStyle(fontWeight: FontWeight.w900))),
                      title: Text(group.key, style: const TextStyle(fontWeight: FontWeight.w800)),
                      subtitle: Text('${group.value.length} 首服务器歌曲'),
                      trailing: const Icon(Icons.chevron_right),
                    ));
                  },
                ) : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  itemCount: songs.length,
                  itemBuilder: (context, index) {
                    final song = songs[index];
                    return Card(child: ListTile(
                      onTap: () => unawaited(playSong(song)),
                      leading: CircleAvatar(
                        backgroundColor: accent.withValues(alpha: .16),
                        foregroundImage: artistImage(song),
                        child: const Icon(Icons.play_arrow),
                      ),
                      title: Text(song.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800)),
                      subtitle: Text('${song.artist} · ${song.language} · ${song.genre}'),
                      trailing: FilledButton.tonal(
                        onPressed: () => unawaited(processSong(song)),
                        child: Text(song.isAiReady ? '打开成果' : '处理中'),
                      ),
                    ));
                  },
                ),
        ),
      ]);
  }
}

class PipelinePage extends StatelessWidget {
  const PipelinePage({super.key, required this.store});
  final AppStore store;
  static const stages = ['读取', '六轨+电吉他', '分析', '和弦', '乐谱', '改编', '渲染', '入库'];

  Future<bool> _confirmDelete(
    BuildContext context, {
    required String title,
    required String message,
  }) async {
    return await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: Text(title),
            content: Text(message),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('取消'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('删除'),
              ),
            ],
          ),
        ) ??
        false;
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        PageHeader(
          title: '自动生产流水线',
          subtitle: '失败可续跑，任务状态自动保存',
          action: store.jobs.any((job) => job.status == '完成' || job.status == '失败')
              ? OutlinedButton.icon(
                  onPressed: () => unawaited(() async {
                    final confirmed = await _confirmDelete(
                      context,
                      title: '清空已结束任务？',
                      message: '将清除所有已完成和失败的任务记录，不会删除原始歌曲或服务器曲库文件。',
                    );
                    if (confirmed) await store.clearFinishedJobs();
                  }()),
                  icon: const Icon(Icons.delete_sweep_outlined),
                  label: const Text('清理'),
                )
              : null,
        ),
        Expanded(
          child: store.jobs.isEmpty
              ? const EmptyState(icon: Icons.auto_awesome, title: '没有待处理歌曲', detail: '请先到音乐库导入歌曲。')
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 28),
                  itemCount: store.jobs.length,
                  itemBuilder: (context, i) {
                    final job = store.jobs[i];
                    return Card(child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        JobCard(job: job, embedded: true),
                        const SizedBox(height: 12),
                        LinearProgressIndicator(value: job.progress, minHeight: 8, borderRadius: BorderRadius.circular(8)),
                        const SizedBox(height: 8),
                        Text('${(job.progress * 100).round()}% · ${job.stage}', style: const TextStyle(color: Color(0xFFD5C1CB))),
                        const SizedBox(height: 10),
                        Wrap(spacing: 6, runSpacing: 6, children: [
                          for (var s = 0; s < stages.length; s++)
                            Chip(
                              visualDensity: VisualDensity.compact,
                              avatar: Icon(job.progress >= (s + 1) / stages.length ? Icons.check_circle : Icons.circle_outlined, size: 17),
                              label: Text(stages[s]),
                            ),
                        ]),
                        if (job.error.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Text(job.error, style: const TextStyle(color: Colors.redAccent)),
                        ],
                        const SizedBox(height: 10),
                        Row(children: [
                          Expanded(child: FilledButton.icon(
                            onPressed: job.isRunning ? null : () => unawaited(job.serverJobId.isEmpty ? store.startJob(job) : store.resumeJob(job)),
                            icon: Icon(job.serverJobId.isEmpty ? Icons.play_arrow : Icons.refresh),
                            label: Text(job.serverJobId.isEmpty ? '开始自动流水线' : (job.isDone ? '刷新结果' : '继续任务')),
                          )),
                          if (!job.isRunning) ...[
                            const SizedBox(width: 8),
                            OutlinedButton.icon(
                              onPressed: () => unawaited(() async {
                                final confirmed = await _confirmDelete(
                                  context,
                                  title: '删除任务记录？',
                                  message: '将从流水线移除“${job.fileName}”，不会删除原始歌曲或服务器曲库文件。',
                                );
                                if (confirmed) await store.removeJob(job);
                              }()),
                              icon: const Icon(Icons.delete_outline),
                              label: const Text('删除'),
                            ),
                          ],
                        ]),
                      ]),
                    ));
                  },
                ),
        ),
      ]);
}

class PerformancePage extends StatefulWidget {
  const PerformancePage({super.key, required this.store});
  final AppStore store;

  @override
  State<PerformancePage> createState() => _PerformancePageState();
}

class _PerformancePageState extends State<PerformancePage> {
  String? selectedId;
  String scoreType = '和弦谱';
  final levels = <String, double>{'人声': .9, '鼓': .82, '贝斯': .8, '木吉他': .84, '电吉他': .84, '钢琴': .76, '其他': .65};
  final players = <String, AudioPlayer>{};
  StreamSubscription<Duration>? positionSub;
  StreamSubscription<Duration?>? durationSub;
  Duration position = Duration.zero;
  Duration duration = Duration.zero;
  bool dragging = false;
  double dragSeconds = 0;
  String loadedJobId = '';
  static const notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

  PipelineJob? get selected {
    if (widget.store.jobs.isEmpty) return null;
    return widget.store.jobs.firstWhere((e) => e.id == selectedId, orElse: () => widget.store.jobs.first);
  }

  Future<void> loadPlayers(PipelineJob job) async {
    if (loadedJobId == job.id) return;
    await stopPlayers();
    const keys = {
      '人声': 'stem_vocals', '鼓': 'stem_drums', '贝斯': 'stem_bass',
      '木吉他': 'stem_guitar', '电吉他': 'stem_electric_guitar',
      '钢琴': 'stem_piano', '其他': 'stem_other',
    };
    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;
    for (final entry in keys.entries) {
      final url = job.artifacts[entry.value];
      if (url == null || url.isEmpty) continue;
      final player = AudioPlayer();
      try {
        await player.setUrl(url, headers: token.isEmpty ? null : {'Authorization': 'Bearer $token'});
        await player.setVolume(levels[entry.key] ?? .8);
        players[entry.key] = player;
      } catch (_) {
        await player.dispose();
      }
    }
    loadedJobId = job.id;
    if (players.isNotEmpty) {
      final master = players.values.first;
      positionSub = master.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
      durationSub = master.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
    }
    if (mounted) setState(() {});
  }

  Future<void> stopPlayers() async {
    await positionSub?.cancel();
    await durationSub?.cancel();
    for (final player in players.values) { await player.dispose(); }
    players.clear();
    loadedJobId = '';
    position = Duration.zero;
    duration = Duration.zero;
  }

  Future<void> togglePlay() async {
    if (players.isEmpty) return;
    final playing = players.values.first.playing;
    for (final player in players.values) { playing ? await player.pause() : unawaited(player.play()); }
    if (mounted) setState(() {});
  }

  Future<void> seekAll(double seconds) async {
    final target = Duration(milliseconds: (seconds * 1000).round());
    await Future.wait(players.values.map((player) => player.seek(target)));
    if (mounted) setState(() { position = target; dragging = false; });
  }

  @override
  void dispose() {
    unawaited(stopPlayers());
    super.dispose();
  }

  String transpose(String key, int semitones) {
    final index = notes.indexOf(key);
    if (index < 0) return key;
    return notes[(index + semitones) % 12];
  }

  int capoFor(String key) {
    final target = notes.indexOf(key);
    if (target < 0) return 0;
    const easy = {'C', 'G', 'D', 'A', 'E'};
    for (var capo = 0; capo <= 7; capo++) {
      final shape = notes[(target - capo) % 12];
      if (easy.contains(shape)) return capo;
    }
    return 0;
  }

  @override
  Widget build(BuildContext context) {
    final job = selected;
    if (job == null) {
      return const Column(children: [
        PageHeader(title: '现场演出', subtitle: '升降调、分轨混音与乐手谱面'),
        Expanded(child: EmptyState(icon: Icons.piano, title: '请先导入歌曲', detail: '完成分析后即可进入演出模式。')),
      ]);
    }
    selectedId ??= job.id;
    if (loadedJobId != job.id && job.isDone) {
      WidgetsBinding.instance.addPostFrameCallback((_) => loadPlayers(job));
    }
    final currentKey = transpose(job.originalKey, job.semitones);
    final capo = capoFor(currentKey);
    final artifactKey = {'和弦谱': 'lead_sheet', '五线谱': 'musicxml', '六线谱': 'guitar_tab', '木吉他谱': 'acoustic_guitar_tab', '电吉他谱': 'electric_guitar_tab', '贝斯谱': 'bass_score', '鼓谱': 'drum_score', '键盘谱': 'piano_score'}[scoreType];
    final artifact = job.artifacts[artifactKey];
    const trackKeys = {'人声': 'stem_vocals', '鼓': 'stem_drums', '贝斯': 'stem_bass', '木吉他': 'stem_guitar', '电吉他': 'stem_electric_guitar', '钢琴': 'stem_piano', '其他': 'stem_other'};
    return Column(children: [
      const PageHeader(title: '现场演出', subtitle: '所有音轨、和弦和谱面同步变调'),
      Expanded(child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 30), children: [
        DropdownButtonFormField<String>(
          initialValue: selectedId,
          items: widget.store.jobs.map((e) => DropdownMenuItem(value: e.id, child: Text(e.fileName, overflow: TextOverflow.ellipsis))).toList(),
          onChanged: (value) => setState(() => selectedId = value),
          decoration: const InputDecoration(labelText: '当前歌曲'),
        ),
        const SizedBox(height: 12),
        Card(child: Padding(padding: const EdgeInsets.all(18), child: Column(children: [
          Text('原调 ${job.originalKey}', style: const TextStyle(color: Color(0xFFBDAAB5))),
          Text(currentKey, style: const TextStyle(fontSize: 64, fontWeight: FontWeight.w900)),
          Text('${job.semitones >= 0 ? '+' : ''}${job.semitones} 半音 · 吉他 Capo ${capo == 0 ? '不夹' : '$capo 品'}', style: const TextStyle(color: accent, fontWeight: FontWeight.w700)),
          Slider(value: job.semitones.toDouble(), min: -12, max: 12, divisions: 24, label: '${job.semitones}', onChanged: (value) => widget.store.setTranspose(job, value.round())),
          Row(children: [
            Expanded(child: OutlinedButton(onPressed: () => widget.store.setTranspose(job, job.semitones - 1), child: const Text('降半音'))),
            const SizedBox(width: 8),
            Expanded(child: OutlinedButton(onPressed: () => widget.store.setTranspose(job, 0), child: const Text('恢复原调'))),
            const SizedBox(width: 8),
            Expanded(child: FilledButton(onPressed: () => widget.store.setTranspose(job, job.semitones + 1), child: const Text('升半音'))),
          ]),
        ]))),
        const SizedBox(height: 12),
        Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(children: [
          Row(children: [
            IconButton.filled(onPressed: players.isEmpty ? null : togglePlay, icon: Icon(players.isNotEmpty && players.values.first.playing ? Icons.pause : Icons.play_arrow)),
            const SizedBox(width: 10),
            Expanded(child: Slider(
              value: (dragging ? dragSeconds : position.inMilliseconds / 1000).clamp(0, duration.inMilliseconds / 1000 > 0 ? duration.inMilliseconds / 1000 : 1).toDouble(),
              max: duration.inMilliseconds > 0 ? duration.inMilliseconds / 1000 : 1,
              onChangeStart: (value) => setState(() { dragging = true; dragSeconds = value; }),
              onChanged: (value) => setState(() => dragSeconds = value),
              onChangeEnd: seekAll,
            )),
            Text('${position.inMinutes}:${(position.inSeconds % 60).toString().padLeft(2, '0')} / ${duration.inMinutes}:${(duration.inSeconds % 60).toString().padLeft(2, '0')}'),
          ]),
          const Text('拖动后会同步定位所有音轨，不再自动跳回原播放位置。', style: TextStyle(color: Color(0xFFBDAAB5))),
        ]))),
        const SizedBox(height: 12),
        const Text('六轨基础 + 电吉他二次分离混音', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        Card(child: Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Column(children: [
          for (final entry in levels.entries)
            ListTile(
              leading: Icon(entry.key == '鼓' ? Icons.album : Icons.multitrack_audio, color: accent),
              title: Text(entry.key),
              subtitle: Slider(value: entry.value, onChanged: (value) { setState(() => levels[entry.key] = value); players[entry.key]?.setVolume(value); }),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                Text('${(entry.value * 100).round()}%'),
                if (job.artifacts[trackKeys[entry.key]] != null)
                  IconButton(
                    onPressed: () => Clipboard.setData(ClipboardData(text: job.artifacts[trackKeys[entry.key]]!)),
                    icon: const Icon(Icons.download_for_offline_outlined),
                    tooltip: '复制音轨下载地址',
                  ),
              ]),
            ),
        ]))),
        const SizedBox(height: 12),
        const Text('乐手谱面', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        Wrap(spacing: 7, runSpacing: 7, children: [
          for (final type in const ['和弦谱', '五线谱', '六线谱', '木吉他谱', '电吉他谱', '贝斯谱', '鼓谱', '键盘谱'])
            ChoiceChip(label: Text(type), selected: scoreType == type, onSelected: (_) => setState(() => scoreType = type)),
        ]),
        const SizedBox(height: 10),
        Card(child: Padding(padding: const EdgeInsets.all(18), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(scoreType, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Text(artifact == null ? '流水线完成后，这里会显示服务器生成的$scoreType。' : '谱面已生成，可复制地址后打开或下载。', style: const TextStyle(color: Color(0xFFBDAAB5))),
          if (job.artifacts['score_data'] != null) ...[
            const SizedBox(height: 12),
            ScorePreview(url: job.artifacts['score_data']!, token: widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken, tablature: scoreType == '六线谱' || scoreType == '木吉他谱' || scoreType == '电吉他谱', positionSeconds: position.inMilliseconds / 1000),
          ],
          if (artifact != null) ...[
            const SizedBox(height: 10),
            FilledButton.icon(onPressed: () => Clipboard.setData(ClipboardData(text: artifact)), icon: const Icon(Icons.copy), label: const Text('复制谱面地址')),
          ],
        ]))),
        const SizedBox(height: 12),
        const Text('Setlist 演出歌单', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        Card(child: Column(children: [
          for (var i = 0; i < widget.store.jobs.length; i++)
            ListTile(
              leading: CircleAvatar(backgroundColor: i == 0 ? accent : const Color(0xFF432B39), child: Text('${i + 1}')),
              title: Text(widget.store.jobs[i].fileName, maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: Text(widget.store.jobs[i].isDone ? '六轨、电吉他与谱面就绪' : widget.store.jobs[i].stage),
              trailing: IconButton(onPressed: () => setState(() => selectedId = widget.store.jobs[i].id), icon: const Icon(Icons.play_arrow)),
            ),
        ])),
      ])),
    ]);
  }
}

class ScorePreview extends StatefulWidget {
  const ScorePreview({super.key, required this.url, required this.token, required this.tablature, required this.positionSeconds});
  final String url;
  final String token;
  final bool tablature;
  final double positionSeconds;

  @override
  State<ScorePreview> createState() => _ScorePreviewState();
}

class _ScorePreviewState extends State<ScorePreview> {
  List<Map<String, dynamic>> notes = const [];
  List<Map<String, dynamic>> lyrics = const [];
  List<Map<String, dynamic>> lyricUnits = const [];
  String lyricsMessage = '';

  @override
  void initState() {
    super.initState();
    unawaited(load());
  }

  @override
  void didUpdateWidget(covariant ScorePreview oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.url != widget.url || oldWidget.tablature != widget.tablature) unawaited(load());
  }

  Future<void> load() async {
    final client = HttpClient();
    try {
      final request = await client.getUrl(Uri.parse(widget.url));
      if (widget.token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer ${widget.token}');
      final response = await request.close();
      final body = await response.transform(utf8.decoder).join();
      if (response.statusCode >= 200 && response.statusCode < 300) {
        final data = Map<String, dynamic>.from(jsonDecode(body) as Map);
        final rows = data[widget.tablature ? 'tab_notes' : 'staff_notes'];
        final lyricRows = data['lyrics'];
        final unitRows = data['lyric_units'];
        if (mounted) setState(() {
          notes = rows is List ? rows.map((e) => Map<String, dynamic>.from(e as Map)).toList() : const [];
          lyrics = lyricRows is List ? lyricRows.map((e) => Map<String, dynamic>.from(e as Map)).toList() : const [];
          lyricUnits = unitRows is List ? unitRows.map((e) => Map<String, dynamic>.from(e as Map)).toList() : const [];
          lyricsMessage = '${data['lyrics_message'] ?? ''}';
        });
      }
    } finally {
      client.close(force: true);
    }
  }

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 230,
        child: CustomPaint(
          painter: ScorePainter(notes: notes, lyrics: lyrics, lyricUnits: lyricUnits, lyricsMessage: lyricsMessage, tablature: widget.tablature, positionSeconds: widget.positionSeconds),
          size: Size.infinite,
        ),
      );
}

class ScorePainter extends CustomPainter {
  ScorePainter({required this.notes, required this.lyrics, required this.lyricUnits, required this.lyricsMessage, required this.tablature, required this.positionSeconds});
  final List<Map<String, dynamic>> notes;
  final List<Map<String, dynamic>> lyrics;
  final List<Map<String, dynamic>> lyricUnits;
  final String lyricsMessage;
  final bool tablature;
  final double positionSeconds;

  @override
  void paint(Canvas canvas, Size size) {
    final linePaint = Paint()..color = const Color(0xFFBDAAB5)..strokeWidth = 1;
    final text = TextPainter(textDirection: TextDirection.ltr);
    final lineCount = tablature ? 6 : 5;
    const top = 35.0;
    const gap = 18.0;
    for (var i = 0; i < lineCount; i++) {
      canvas.drawLine(Offset(12, top + i * gap), Offset(size.width - 12, top + i * gap), linePaint);
    }
    final visible = notes.where((note) {
      final start = (note['start'] as num?)?.toDouble() ?? 0;
      return start >= positionSeconds - 1 && start <= positionSeconds + 15;
    }).take(24).toList();
    for (var i = 0; i < visible.length; i++) {
      final note = visible[i];
      final x = 28 + i * ((size.width - 56) / 24);
      final noteStart = (note['start'] as num?)?.toDouble() ?? 0;
      final noteDuration = (note['duration'] as num?)?.toDouble() ?? .1;
      final active = positionSeconds >= noteStart && positionSeconds <= noteStart + noteDuration;
      final activeNotePaint = Paint()..color = active ? orangeSoft : accent;
      if (tablature) {
        final string = ((note['string'] as num?)?.toInt() ?? 1).clamp(1, 6);
        final fret = (note['fret'] as num?)?.toInt() ?? 0;
        text.text = TextSpan(text: '$fret', style: TextStyle(color: active ? orangeSoft : accent, fontSize: 14, fontWeight: FontWeight.bold));
        text.layout();
        text.paint(canvas, Offset(x - text.width / 2, top + (string - 1) * gap - text.height / 2));
      } else {
        final midi = (note['midi'] as num?)?.toInt() ?? 60;
        final y = (top + 4 * gap - (midi - 60) * gap / 3.5).clamp(16.0, 132.0);
        canvas.drawOval(Rect.fromCenter(center: Offset(x, y), width: 12, height: 9), activeNotePaint);
        canvas.drawLine(Offset(x + 5, y), Offset(x + 5, y - 28), activeNotePaint..strokeWidth = 1.5);
      }
      final noteLyric = '${note['lyric'] ?? ''}';
      if (noteLyric.isNotEmpty) {
        text.text = TextSpan(text: noteLyric, style: TextStyle(color: active ? Colors.white : const Color(0xFFBDAAB5), fontSize: 13, fontWeight: active ? FontWeight.w800 : FontWeight.w500, fontFamilyFallback: const ['PingFang SC', 'Noto Sans CJK SC', 'Microsoft YaHei']));
        text.layout(maxWidth: 28);
        text.paint(canvas, Offset(x - text.width / 2, top + lineCount * gap + 5));
      }
    }
    if (visible.isEmpty) {
      text.text = TextSpan(text: notes.isEmpty ? '正在读取谱面…' : '当前播放位置附近无主旋律音符', style: const TextStyle(color: Color(0xFFBDAAB5)));
      text.layout();
      text.paint(canvas, Offset((size.width - text.width) / 2, 142));
    }
    var currentLyric = '';
    for (final row in lyrics) {
      if (((row['start'] as num?)?.toDouble() ?? 0) <= positionSeconds) {
        currentLyric = '${row['text'] ?? ''}';
      } else {
        break;
      }
    }
    Map<String, dynamic>? currentUnit;
    for (final unit in lyricUnits) {
      if (((unit['start'] as num?)?.toDouble() ?? 0) <= positionSeconds) {
        currentUnit = unit;
      } else {
        break;
      }
    }
    final currentLine = (currentUnit?['line'] as num?)?.toInt();
    final lineUnits = currentLine == null ? const <Map<String, dynamic>>[] : lyricUnits.where((row) => (row['line'] as num?)?.toInt() == currentLine).toList();
    if (lineUnits.isNotEmpty) {
      text.text = TextSpan(children: [
        for (final unit in lineUnits)
          TextSpan(
            text: '${unit['text'] ?? ''}',
            style: TextStyle(
              color: positionSeconds >= ((unit['end'] as num?)?.toDouble() ?? 0)
                  ? accent
                  : positionSeconds >= ((unit['start'] as num?)?.toDouble() ?? 0)
                      ? Colors.white
                      : const Color(0xFF776A73),
              fontSize: 19,
              fontWeight: positionSeconds >= ((unit['start'] as num?)?.toDouble() ?? 0) && positionSeconds < ((unit['end'] as num?)?.toDouble() ?? 0) ? FontWeight.w900 : FontWeight.w600,
              fontFamilyFallback: const ['PingFang SC', 'Noto Sans CJK SC', 'Microsoft YaHei'],
            ),
          ),
      ]);
      text.layout(maxWidth: size.width - 28);
      text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 8));
    } else if (currentLyric.isNotEmpty) {
      text.text = TextSpan(text: currentLyric, style: const TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.w700, fontFamilyFallback: ['PingFang SC', 'Noto Sans CJK SC', 'Microsoft YaHei']));
      text.layout(maxWidth: size.width - 28);
      text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 4));
    } else if (lyrics.isEmpty && lyricsMessage.isNotEmpty) {
      text.text = TextSpan(text: lyricsMessage, style: const TextStyle(color: Color(0xFFFFB45E), fontSize: 12));
      text.layout(maxWidth: size.width - 28);
      text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 4));
    }
  }

  @override
  bool shouldRepaint(covariant ScorePainter oldDelegate) => oldDelegate.notes != notes || oldDelegate.lyrics != lyrics || oldDelegate.lyricUnits != lyricUnits || oldDelegate.lyricsMessage != lyricsMessage || oldDelegate.tablature != tablature || oldDelegate.positionSeconds != positionSeconds;
}

class CommunityPage extends StatefulWidget {
  const CommunityPage({super.key, required this.store});
  final AppStore store;

  @override
  State<CommunityPage> createState() => _CommunityPageState();
}

class _CommunityPageState extends State<CommunityPage> {
  final account = TextEditingController();
  final password = TextEditingController();
  final nickname = TextEditingController();
  final message = TextEditingController();
  bool registerMode = false;
  bool busy = false;

  @override
  void dispose() {
    account.dispose();
    password.dispose();
    nickname.dispose();
    message.dispose();
    super.dispose();
  }

  Future<void> submitAccount() async {
    setState(() => busy = true);
    try {
      await widget.store.authenticate(
        account: account.text,
        phoneValue: '',
        password: password.text,
        register: registerMode,
        nicknameValue: nickname.text,
      );
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(registerMode ? '注册并登录成功' : '登录成功')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> send() async {
    if (message.text.trim().isEmpty) return;
    setState(() => busy = true);
    try {
      await widget.store.sendCommunity(message.text);
      message.clear();
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String timeLabel(double seconds) {
    final time = DateTime.fromMillisecondsSinceEpoch((seconds * 1000).round()).toLocal();
    return '${time.month.toString().padLeft(2, '0')}-${time.day.toString().padLeft(2, '0')} ${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final loggedIn = widget.store.accountToken.isNotEmpty;
    return Column(children: [
      PageHeader(
        title: '内测群聊',
        subtitle: loggedIn ? '${widget.store.nickname} · 已登录' : '账号登录后进入橘味儿音乐内测群',
        action: IconButton(onPressed: loggedIn ? widget.store.refreshCommunity : null, icon: const Icon(Icons.refresh)),
      ),
      Expanded(child: loggedIn ? buildChat() : buildLogin()),
    ]);
  }

  Widget buildLogin() => ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 30), children: [
        Card(child: Padding(padding: const EdgeInsets.all(18), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SegmentedButton<bool>(
            segments: const [ButtonSegment(value: false, label: Text('登录')), ButtonSegment(value: true, label: Text('注册'))],
            selected: {registerMode},
            onSelectionChanged: (value) => setState(() => registerMode = value.first),
          ),
          const SizedBox(height: 14),
          TextField(controller: account, decoration: const InputDecoration(labelText: '账号', hintText: '中文、字母或数字，至少3位')),
          const SizedBox(height: 10),
          if (registerMode) ...[
            TextField(controller: nickname, decoration: const InputDecoration(labelText: '群聊昵称（可选）')),
            const SizedBox(height: 10),
          ],
          TextField(controller: password, obscureText: true, decoration: const InputDecoration(labelText: '密码（至少6位）')),
          const SizedBox(height: 14),
          FilledButton.icon(onPressed: busy ? null : submitAccount, icon: const Icon(Icons.login), label: Text(registerMode ? '注册并登录' : '登录')),
          const SizedBox(height: 10),
          const Text('AI 服务：应用自动连接，无需手动设置', style: TextStyle(color: Color(0xFFBDAAB5))),
        ]))),
      ]);

  Widget buildChat() => Column(children: [
        Expanded(
          child: widget.store.communityMessages.isEmpty
              ? const EmptyState(icon: Icons.forum, title: '内测群暂无消息', detail: '发送第一条消息，和其他内测用户交流使用反馈。')
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  itemCount: widget.store.communityMessages.length,
                  itemBuilder: (context, index) {
                    final item = widget.store.communityMessages[index];
                    return Card(child: ListTile(
                      leading: CircleAvatar(backgroundColor: accent.withValues(alpha: .18), child: Text(item.nickname.isEmpty ? '橘' : item.nickname.substring(0, 1))),
                      title: Text(item.nickname, style: const TextStyle(fontWeight: FontWeight.w800)),
                      subtitle: Text(item.content),
                      trailing: Text(timeLabel(item.createdAt), style: const TextStyle(fontSize: 11, color: Color(0xFFBDAAB5))),
                    ));
                  },
                ),
        ),
        SafeArea(top: false, child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
          child: Row(children: [
            Expanded(child: TextField(controller: message, minLines: 1, maxLines: 4, decoration: const InputDecoration(hintText: '发送内测交流消息…'))),
            const SizedBox(width: 8),
            IconButton.filled(onPressed: busy ? null : send, icon: const Icon(Icons.send)),
            IconButton(onPressed: widget.store.logout, icon: const Icon(Icons.logout), tooltip: '退出登录'),
          ]),
        )),
      ]);
}

class ProfilePage extends StatefulWidget {
  const ProfilePage({super.key, required this.store});
  final AppStore store;

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  late final TextEditingController avatar;
  late final TextEditingController nickname;
  late final TextEditingController bio;
  late final TextEditingController origin;
  late final TextEditingController address;
  late final TextEditingController wechat;
  late String gender;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    avatar = TextEditingController(text: widget.store.avatarUrl);
    nickname = TextEditingController(text: widget.store.nickname);
    bio = TextEditingController(text: widget.store.bio);
    origin = TextEditingController(text: widget.store.origin);
    address = TextEditingController(text: widget.store.address);
    wechat = TextEditingController(text: widget.store.wechat);
    gender = widget.store.gender;
  }

  @override
  void dispose() {
    avatar.dispose(); nickname.dispose(); bio.dispose(); origin.dispose(); address.dispose(); wechat.dispose();
    super.dispose();
  }

  Future<void> save() async {
    setState(() => busy = true);
    try {
      await widget.store.updateProfile({
        'avatar_url': avatar.text.trim(), 'nickname': nickname.text.trim(), 'gender': gender,
        'bio': bio.text.trim(), 'origin': origin.text.trim(), 'address': address.text.trim(), 'wechat': wechat.text.trim(),
      });
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('个人资料已保存')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('个人设置')),
    body: ListView(padding: const EdgeInsets.all(18), children: [
      Center(child: CircleAvatar(
        radius: 50, backgroundColor: const Color(0xFF432B39),
        foregroundImage: avatar.text.trim().isEmpty ? null : NetworkImage(avatar.text.trim()),
        child: Text(widget.store.nickname.isEmpty ? '橘' : widget.store.nickname.substring(0, 1), style: const TextStyle(fontSize: 32, fontWeight: FontWeight.w900)),
      )),
      const SizedBox(height: 10),
      Center(child: Text('${widget.store.username} · ${widget.store.phone}', style: const TextStyle(color: Color(0xFFBDAAB5)))),
      const SizedBox(height: 18),
      TextField(controller: avatar, decoration: const InputDecoration(labelText: '头像图片地址（可选）')),
      const SizedBox(height: 10),
      TextField(controller: nickname, decoration: const InputDecoration(labelText: '昵称')),
      const SizedBox(height: 10),
      DropdownButtonFormField<String>(value: gender, decoration: const InputDecoration(labelText: '性别'), items: const ['保密','男','女','其他'].map((value) => DropdownMenuItem(value: value, child: Text(value))).toList(), onChanged: (value) { if (value != null) setState(() => gender = value); }),
      const SizedBox(height: 10),
      TextField(controller: bio, minLines: 3, maxLines: 5, decoration: const InputDecoration(labelText: '个人资料 / 简介')),
      const SizedBox(height: 10),
      TextField(controller: origin, decoration: const InputDecoration(labelText: '籍贯')),
      const SizedBox(height: 10),
      TextField(controller: address, decoration: const InputDecoration(labelText: '住址')),
      const SizedBox(height: 10),
      TextField(controller: wechat, decoration: const InputDecoration(labelText: '微信号')),
      const SizedBox(height: 18),
      FilledButton.icon(onPressed: busy ? null : save, icon: const Icon(Icons.save), label: const Text('保存个人资料')),
      const SizedBox(height: 10),
      OutlinedButton.icon(onPressed: busy ? null : () async { await widget.store.logout(); if (mounted) Navigator.pop(context); }, icon: const Icon(Icons.logout), label: const Text('退出登录')),
    ]),
  );
}

class LyricsStudioPage extends StatefulWidget {
  const LyricsStudioPage({super.key, required this.store});
  final AppStore store;

  @override
  State<LyricsStudioPage> createState() => _LyricsStudioPageState();
}

class _LyricsStudioPageState extends State<LyricsStudioPage> {
  final theme = TextEditingController();
  String language = '普通话';
  String style = '流行';
  String mood = '温暖';
  bool busy = false;
  List<Map<String, dynamic>> variants = [];
  int selected = 0;

  @override
  void dispose() { theme.dispose(); super.dispose(); }

  Future<void> generate() async {
    if (theme.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('请填写歌词主题')));
      return;
    }
    setState(() => busy = true);
    try {
      final data = await widget.store.generateLyrics({
        'theme': theme.text.trim(), 'language': language, 'style': style,
        'mood': mood, 'variants': 3, 'bpm': 72,
      });
      final rows = (data['variants'] as List? ?? const [])
          .map((e) => Map<String, dynamic>.from(e as Map)).toList();
      if (mounted) setState(() { variants = rows; selected = 0; });
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('AI 歌词生成失败：$error')));
    } finally { if (mounted) setState(() => busy = false); }
  }

  Future<void> copyValue(String key) async {
    if (variants.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: '${variants[selected][key] ?? ''}'));
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制到剪贴板')));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(child: Column(children: [
      PageHeader(title: 'AI 歌词创作', subtitle: '普通话 / 粤语·可编辑初稿', action: IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.close))),
      Expanded(child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 28), children: [
        Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(children: [
          TextField(controller: theme, maxLength: 80, decoration: const InputDecoration(labelText: '主题 / 故事', hintText: '例：离开家乡后的重逢')),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: DropdownButtonFormField(value: language, items: const ['普通话','粤语','英语'].map((e) => DropdownMenuItem(value:e, child:Text(e))).toList(), onChanged: (v) => setState(() => language=v!))),
            const SizedBox(width: 8),
            Expanded(child: DropdownButtonFormField(value: style, items: const ['流行','摇滚','民谣','R&B'].map((e) => DropdownMenuItem(value:e, child:Text(e))).toList(), onChanged: (v) => setState(() => style=v!))),
            const SizedBox(width: 8),
            Expanded(child: DropdownButtonFormField(value: mood, items: const ['温暖','热血','伤感','治愈'].map((e) => DropdownMenuItem(value:e, child:Text(e))).toList(), onChanged: (v) => setState(() => mood=v!))),
          ]),
          const SizedBox(height: 12),
          FilledButton.icon(onPressed: busy ? null : generate, icon: const Icon(Icons.auto_awesome), label: Text(busy ? '生成中…' : '生成 3 个方案')),
          if (language == '粤语') const Padding(padding: EdgeInsets.only(top: 10), child: Text('粤语生成支持常用口语，但发音、押韵和地域用词仍需母语使用者复核。', style: TextStyle(color: Color(0xFFFFB36B)))),
        ]))),
        if (variants.isNotEmpty) ...[
          const SizedBox(height: 12),
          SegmentedButton<int>(segments: List.generate(variants.length, (i) => ButtonSegment(value:i,label:Text('方案 ${i+1}'))), selected:{selected}, onSelectionChanged:(v)=>setState(()=>selected=v.first)),
          const SizedBox(height: 10),
          Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('${variants[selected]['title']}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            SelectableText('${variants[selected]['lyrics']}', style: const TextStyle(height: 1.7)),
            const SizedBox(height: 12),
            Text('${variants[selected]['notice']}', style: const TextStyle(color: Color(0xFFFFB36B))),
            const SizedBox(height: 12),
            Row(children:[Expanded(child:OutlinedButton.icon(onPressed:()=>copyValue('lyrics'),icon:const Icon(Icons.copy),label:const Text('复制 TXT'))),const SizedBox(width:8),Expanded(child:OutlinedButton.icon(onPressed:()=>copyValue('lrc'),icon:const Icon(Icons.sync),label:const Text('复制 LRC')))]),
          ]))),
        ],
      ])),
    ])),
  );
}

const openSourceNotice = '''
橘味儿音乐感谢开源社区。移动端使用 Flutter、Dart、file_picker、shared_preferences、just_audio 与 cupertino_icons；服务器/电脑端使用 FastAPI、PyTorch、Demucs、audio-separator/UVR、NumPy、SciPy、librosa 和 PySide6 等组件。

各组件的版权、商标与许可证归其权利人所有，实际许可条款以随包许可证和官方项目声明为准。本软件不宣称对这些组件享有额外权利。
''';

const privacyPolicy = '''
我们为完成用户选择的 AI 分轨、谱面、歌词初稿和编配任务，会处理用户主动导入的音频、任务参数及生成结果。账号功能会保存账号、昵称、加密密码摘要和会话令牌；反馈功能会保存用户主动填写的内容、联系方式与设备信息。

手机端会把需要 AI 处理的音频上传到配置的橘味儿 AI 服务。未经用户操作，不会自动读取其他文件。用户可在应用内删除本地任务，并通过“帮助与反馈”申请查询或删除服务端资料。
''';

const userAgreement = '''
1. 本软件目前仅供学习与研究使用，不提供歌曲下载服务。
2. 用户只能导入自己创作、已获授权或依法可使用的音频，不得绕过 DRM、会员、付费、登录验证或平台访问控制。
3. AI 分析、歌词、乐谱与编配均可能出现偏差，演出、发行或商业使用前必须人工复核。
4. 用户对导入内容、生成结果的合法性及后续使用负责，不得用于侵权、诈骗或其他违法用途。
5. 测试阶段功能和服务可能调整；重要工程请自行备份。
''';

const aboutSoftware = '''
橘味儿音乐 v3.3.0
AI 音乐工作站·Android / iOS / Windows

核心功能：六轨基础分离与电吉他二次识别、五线谱/六线谱/歌词同步、AI 歌词初稿、智能编配、乐手练习与现场演出。

本软件目前仅供学习与研究使用，不提供歌曲下载服务。
''';

class LegalDocumentPage extends StatelessWidget {
  const LegalDocumentPage({super.key, required this.title, required this.text});
  final String title;
  final String text;
  @override
  Widget build(BuildContext context) => Scaffold(body: SafeArea(child: Column(children: [
    PageHeader(title: title, subtitle: '更新日期：2026-08-18', action: IconButton(onPressed:()=>Navigator.pop(context),icon:const Icon(Icons.close))),
    Expanded(child: ListView(padding: const EdgeInsets.all(18), children: [
      if (title == '关于软件') Center(child: Image.asset('assets/juweier_brand_mark_v322.png', width: 130, height: 130)),
      Card(child: Padding(padding: const EdgeInsets.all(18), child: SelectableText(text, style: const TextStyle(height:1.75, fontSize:16)))),
    ])),
  ])));
}

class FeedbackPage extends StatefulWidget {
  const FeedbackPage({super.key, required this.store});
  final AppStore store;
  @override State<FeedbackPage> createState()=>_FeedbackPageState();
}

class _FeedbackPageState extends State<FeedbackPage> {
  final content=TextEditingController(); final contact=TextEditingController();
  String category='功能建议'; bool busy=false;
  @override void dispose(){content.dispose();contact.dispose();super.dispose();}
  Future<void> submit() async {
    if(content.text.trim().length<2)return;
    setState(()=>busy=true);
    try { await widget.store.submitFeedback({'category':category,'content':content.text.trim(),'contact':contact.text.trim(),'device':Platform.operatingSystem,'app_version':appVersion});
      if(mounted){content.clear();ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content:Text('反馈已提交，感谢你帮助改进。')));}
    } catch(e){if(mounted)ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text('提交失败：$e')));} finally{if(mounted)setState(()=>busy=false);}
  }
  @override Widget build(BuildContext context)=>Scaffold(body:SafeArea(child:Column(children:[
    PageHeader(title:'帮助与反馈',subtitle:'问题、建议与隐私请求',action:IconButton(onPressed:()=>Navigator.pop(context),icon:const Icon(Icons.close))),
    Expanded(child:ListView(padding:const EdgeInsets.all(16),children:[
      const Card(child:Padding(padding:EdgeInsets.all(16),child:Text('常见问题：手机端需要网络连接 AI 服务；谱面和歌词为 AI 识别/生成结果，请在演出前复核。\n\n本软件目前仅供学习与研究使用，不提供歌曲下载服务。'))),
      const SizedBox(height:12),
      DropdownButtonFormField(value:category,items:const ['功能建议','故障反馈','账号问题','隐私/删除请求'].map((e)=>DropdownMenuItem(value:e,child:Text(e))).toList(),onChanged:(v)=>setState(()=>category=v!)),
      const SizedBox(height:10),TextField(controller:content,minLines:5,maxLines:10,decoration:const InputDecoration(labelText:'详细内容')),
      const SizedBox(height:10),TextField(controller:contact,decoration:const InputDecoration(labelText:'联系方式（可选）')),
      const SizedBox(height:12),FilledButton.icon(onPressed:busy?null:submit,icon:const Icon(Icons.send),label:Text(busy?'提交中…':'提交反馈')),
    ])),
  ])));
}

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.store});
  final AppStore store;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  void openDocument(String title, String text) => Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => LegalDocumentPage(title: title, text: text),
  ));

  @override
  Widget build(BuildContext context) => Column(children: [
        PageHeader(
          title: '设置与关于',
          subtitle: '应用、协议与帮助',
          action: Navigator.of(context).canPop() ? IconButton(onPressed: () => Navigator.of(context).pop(), icon: const Icon(Icons.close)) : null,
        ),
        Expanded(child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 30), children: [
          Card(child: ListTile(
            leading: const Icon(Icons.cloud_done_outlined, color: accent),
            title: Text('AI 服务·${widget.store.serverState}'),
            subtitle: const Text('移动端自动连接，无需填写服务器地址'),
            trailing: IconButton(onPressed: widget.store.testServer, icon: const Icon(Icons.refresh)),
          )),
          const SizedBox(height: 12),
          Card(child: Column(children: [
            ListTile(leading: const Icon(Icons.menu_book_outlined), title: const Text('开源软件声明'), trailing: const Icon(Icons.chevron_right), onTap: () => openDocument('开源软件声明', openSourceNotice)),
            const Divider(height: 1),
            ListTile(leading: const Icon(Icons.privacy_tip_outlined), title: const Text('隐私政策'), trailing: const Icon(Icons.chevron_right), onTap: () => openDocument('隐私政策', privacyPolicy)),
            const Divider(height: 1),
            ListTile(leading: const Icon(Icons.gavel_outlined), title: const Text('用户协议'), trailing: const Icon(Icons.chevron_right), onTap: () => openDocument('用户协议', userAgreement)),
            const Divider(height: 1),
            ListTile(leading: const Icon(Icons.help_outline), title: const Text('帮助与反馈'), trailing: const Icon(Icons.chevron_right), onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => FeedbackPage(store: widget.store)))),
            const Divider(height: 1),
            ListTile(leading: const Icon(Icons.info_outline), title: const Text('关于软件'), subtitle: const Text('$appName v$appVersion'), trailing: const Icon(Icons.chevron_right), onTap: () => openDocument('关于软件', aboutSoftware)),
          ])),
          const SizedBox(height: 12),
          const Card(child: Padding(padding: EdgeInsets.all(16), child: Text('本软件目前仅供学习与研究使用，不提供歌曲下载服务。', style: TextStyle(color: Color(0xFFFFB36B), fontWeight: FontWeight.w700)))),
        ])),
      ]);
}

class ServerCard extends StatelessWidget {
  const ServerCard({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) {
    final online = store.serverState == '在线';
    return Card(child: ListTile(
      leading: Container(width: 12, height: 12, decoration: BoxDecoration(shape: BoxShape.circle, color: online ? Colors.greenAccent : Colors.orangeAccent)),
      title: Text('AI 服务器 · ${store.serverState}', style: const TextStyle(fontWeight: FontWeight.w800)),
      subtitle: Text(store.serverDetail, maxLines: 2, overflow: TextOverflow.ellipsis),
      trailing: IconButton(onPressed: store.testServer, icon: const Icon(Icons.refresh)),
    ));
  }
}

class JobCard extends StatelessWidget {
  const JobCard({super.key, required this.job, this.compact = false, this.embedded = false});
  final PipelineJob job;
  final bool compact;
  final bool embedded;

  @override
  Widget build(BuildContext context) {
    final content = ListTile(
      contentPadding: embedded ? EdgeInsets.zero : const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
      leading: CircleAvatar(backgroundColor: accent.withValues(alpha: .14), child: const Icon(Icons.music_note, color: accent)),
      title: Text(job.fileName, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)),
      subtitle: Text('${job.status} · ${job.stage}', maxLines: compact ? 1 : 2, overflow: TextOverflow.ellipsis),
      trailing: Text('${(job.progress * 100).round()}%', style: const TextStyle(color: accent, fontWeight: FontWeight.w800)),
    );
    return embedded ? content : Card(child: content);
  }
}

class PageHeader extends StatelessWidget {
  const PageHeader({super.key, required this.title, required this.subtitle, this.action});
  final String title;
  final String subtitle;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(18, 18, 12, 14),
        child: Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontSize: 27, fontWeight: FontWeight.w900)),
            Text(subtitle, style: const TextStyle(color: Color(0xFFBDAAB5))),
          ])),
          if (action != null) action!,
        ]),
      );
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, required this.detail, this.action});
  final IconData icon;
  final String title;
  final String detail;
  final VoidCallback? action;

  @override
  Widget build(BuildContext context) => Center(child: Padding(
        padding: const EdgeInsets.all(30),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 58, color: accent),
          const SizedBox(height: 12),
          Text(title, style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Text(detail, textAlign: TextAlign.center, style: const TextStyle(color: Color(0xFFBDAAB5))),
          if (action != null) ...[
            const SizedBox(height: 16),
            FilledButton.icon(onPressed: action, icon: const Icon(Icons.add), label: const Text('导入音乐')),
          ],
        ]),
      ));
}

class MetricCard extends StatelessWidget {
  const MetricCard({super.key, required this.label, required this.value, required this.icon});
  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Card(child: Padding(
        padding: const EdgeInsets.all(13),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, color: accent),
          const SizedBox(height: 8),
          Text(value, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900)),
          Text(label, style: const TextStyle(color: Color(0xFFBDAAB5), fontSize: 12)),
        ]),
      ));
}

class FeatureChip extends StatelessWidget {
  const FeatureChip({super.key, required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(color: const Color(0xFF1B121F), borderRadius: BorderRadius.circular(14), border: Border.all(color: const Color(0xFF432B39))),
        child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(icon, color: accent, size: 19), const SizedBox(width: 7), Text(text)]),
      );
}
