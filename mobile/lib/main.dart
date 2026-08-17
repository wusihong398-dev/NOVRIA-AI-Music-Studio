import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

const appName = '橘味儿音乐';
const appVersion = '3.0.0';
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
      artifacts: rawArtifacts is Map
          ? rawArtifacts.map((key, value) => MapEntry('$key', '$value'))
          : <String, String>{},
    );
  }
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
  static const _jobsKey = 'juweier_jobs_v300';
  static const _serverKey = 'juweier_server';
  static const _tokenKey = 'juweier_token';
  static const _accountTokenKey = 'juweier_account_token';
  static const _usernameKey = 'juweier_username';
  static const _nicknameKey = 'juweier_nickname';

  SharedPreferences? _prefs;
  final List<PipelineJob> jobs = [];
  final List<CommunityMessage> communityMessages = [];
  String serverBase = '';
  String apiToken = '';
  String accountToken = '';
  String username = '';
  String nickname = '';
  String accountState = '未登录';
  String serverState = '未配置';
  String serverDetail = '请在设置中填写 Windows/GPU 服务器地址';

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    serverBase = _prefs?.getString(_serverKey) ?? '';
    apiToken = _prefs?.getString(_tokenKey) ?? '';
    accountToken = _prefs?.getString(_accountTokenKey) ?? '';
    username = _prefs?.getString(_usernameKey) ?? '';
    nickname = _prefs?.getString(_nicknameKey) ?? '';
    accountState = accountToken.isEmpty ? '未登录' : '已登录';
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
    if (serverBase.isNotEmpty) unawaited(testServer());
  }

  Future<void> _save() async {
    await _prefs?.setString(_jobsKey, jsonEncode(jobs.map((e) => e.toJson()).toList()));
    await _prefs?.setString(_serverKey, serverBase);
    await _prefs?.setString(_tokenKey, apiToken);
    await _prefs?.setString(_accountTokenKey, accountToken);
    await _prefs?.setString(_usernameKey, username);
    await _prefs?.setString(_nicknameKey, nickname);
  }

  Future<void> saveServer(String base, String token) async {
    serverBase = base.trim().replaceAll(RegExp(r'/+$'), '');
    apiToken = token.trim();
    serverState = serverBase.isEmpty ? '未配置' : '待检测';
    serverDetail = serverBase.isEmpty ? '请填写服务器地址' : serverBase;
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
      final result = await ApiClient(serverBase, apiToken).health();
      serverState = '在线';
      serverDetail = '${result['gpu'] ?? result['device'] ?? '服务器可用'}';
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
    if (!await file.exists()) {
      job.status = '失败';
      job.error = '源文件已不存在，请重新导入';
      await _save();
      notifyListeners();
      return;
    }
    final client = ApiClient(serverBase, accountToken.isNotEmpty ? accountToken : apiToken);
    try {
      job.status = '上传中';
      job.stage = '上传音频';
      job.progress = .03;
      job.error = '';
      await _save();
      notifyListeners();

      final response = await client.submit(job);
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
      job.error = '$error';
      await _save();
      notifyListeners();
    }
  }

  Future<void> resumeJob(PipelineJob job) async {
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
      job.error = '$error';
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
        job.error = '${result['error'] ?? result['message'] ?? '服务器任务失败'}';
      }
      await _save();
      notifyListeners();
      if (job.status != '处理中') break;
      await Future<void>.delayed(const Duration(seconds: 2));
    }
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

  Future<void> authenticate({required String account, required String password, required bool register, String nicknameValue = ''}) async {
    if (serverBase.isEmpty) throw const FormatException('请先配置 AI 服务器地址');
    accountState = register ? '注册中' : '登录中';
    notifyListeners();
    try {
      final result = await ApiClient(serverBase, apiToken).postJson(
        register ? '/api/v1/auth/register' : '/api/v1/auth/login',
        {'username': account.trim(), 'password': password, 'nickname': nicknameValue.trim()},
      );
      accountToken = '${result['token'] ?? ''}';
      if (accountToken.isEmpty) throw const FormatException('服务器没有返回登录令牌');
      username = '${result['username'] ?? account.trim()}';
      nickname = '${result['nickname'] ?? username}';
      accountState = '已登录';
      await _save();
      await refreshCommunity();
    } catch (_) {
      accountState = '登录失败';
      notifyListeners();
      rethrow;
    }
  }

  Future<void> logout() async {
    accountToken = '';
    username = '';
    nickname = '';
    accountState = '未登录';
    communityMessages.clear();
    await _save();
    notifyListeners();
  }

  Future<void> refreshCommunity() async {
    if (accountToken.isEmpty || serverBase.isEmpty) return;
    final result = await ApiClient(serverBase, accountToken).getJson('/api/v1/community/messages?limit=100');
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
    await ApiClient(serverBase, accountToken).postJson('/api/v1/community/messages', {'content': value});
    await refreshCommunity();
  }
}

class ApiClient {
  ApiClient(this.base, this.token);
  final String base;
  final String token;

  Future<Map<String, dynamic>> health() async {
    Object? lastError;
    for (final path in const ['/health', '/api/health']) {
      try {
        return await _jsonRequest('GET', path);
      } catch (error) {
        lastError = error;
      }
    }
    throw Exception(lastError ?? '健康检查失败');
  }

  Future<Map<String, dynamic>> submit(PipelineJob job) async {
    final uri = Uri.parse('$base/api/v1/jobs');
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

      field('arrangement_mode', job.arrangementMode);
      field('transpose', '${job.semitones}');
      field('output', 'wav_mp3');
      request.write('--$boundary\r\n');
      request.write('Content-Disposition: form-data; name="file"; filename="${_safeHeader(job.fileName)}"\r\n');
      request.write('Content-Type: audio/mpeg\r\n\r\n');
      await request.addStream(File(job.path).openRead());
      request.write('\r\n--$boundary--\r\n');
      final response = await request.close().timeout(const Duration(minutes: 10));
      return await _decode(response);
    } finally {
      client.close(force: true);
    }
  }

  Future<Map<String, dynamic>> job(String id) async => _jsonRequest('GET', '/api/v1/jobs/$id');

  Future<Map<String, dynamic>> getJson(String path) => _jsonRequest('GET', path);

  Future<Map<String, dynamic>> postJson(String path, Map<String, dynamic> payload) =>
      _jsonRequest('POST', path, payload: payload);

  Future<Map<String, dynamic>> _jsonRequest(String method, String path, {Map<String, dynamic>? payload}) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
    try {
      final request = await client.openUrl(method, Uri.parse('$base$path'));
      _headers(request);
      if (payload != null) {
        request.headers.contentType = ContentType.json;
        request.write(jsonEncode(payload));
      }
      final response = await request.close().timeout(const Duration(seconds: 20));
      return await _decode(response);
    } finally {
      client.close(force: true);
    }
  }

  void _headers(HttpClientRequest request) {
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    request.headers.set(HttpHeaders.userAgentHeader, 'Juweier-Music/$appVersion');
    if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
  }

  Future<Map<String, dynamic>> _decode(HttpClientResponse response) async {
    final body = await response.transform(utf8.decoder).join();
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw HttpException('HTTP ${response.statusCode}: ${body.length > 240 ? body.substring(0, 240) : body}');
    }
    if (body.trim().isEmpty) return <String, dynamic>{};
    return Map<String, dynamic>.from(jsonDecode(body) as Map);
  }

  String _safeHeader(String value) => value.replaceAll(RegExp(r'[\r\n"]'), '_');
}

class JuweierMusicApp extends StatelessWidget {
  const JuweierMusicApp({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) => MaterialApp(
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
        home: MainShell(store: store),
      );
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
            LibraryPage(store: widget.store, onImport: pickAudio),
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
          ClipRRect(borderRadius: BorderRadius.circular(20), child: Image.asset('assets/juweier_icon.png', width: 66, height: 66)),
          const SizedBox(width: 14),
          const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(appName, style: TextStyle(fontSize: 28, fontWeight: FontWeight.w900)),
            Text('AI 分轨 · 智能改编 · 乐手谱面', style: TextStyle(color: Color(0xFFBDAAB5))),
          ])),
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
          FeatureChip(icon: Icons.multitrack_audio, text: 'AI 六轨分离'),
          FeatureChip(icon: Icons.music_note, text: '自动和弦与段落'),
          FeatureChip(icon: Icons.queue_music, text: '五线谱 / 六线谱'),
          FeatureChip(icon: Icons.tune, text: '升降调与 Capo'),
          FeatureChip(icon: Icons.piano, text: '乐队智能改编'),
          FeatureChip(icon: Icons.live_tv, text: '现场演出模式'),
          FeatureChip(icon: Icons.queue_music, text: 'Setlist 演出歌单'),
          FeatureChip(icon: Icons.forum, text: '账号与内测群聊'),
        ]),
      ],
    );
  }
}

class LibraryPage extends StatelessWidget {
  const LibraryPage({super.key, required this.store, required this.onImport});
  final AppStore store;
  final VoidCallback onImport;

  @override
  Widget build(BuildContext context) => Column(children: [
        PageHeader(title: '音乐库', subtitle: '${store.jobs.length} 首歌曲', action: IconButton(onPressed: onImport, icon: const Icon(Icons.add))),
        Expanded(
          child: store.jobs.isEmpty
              ? EmptyState(icon: Icons.library_music, title: '还没有歌曲', detail: '导入 MP3、WAV、FLAC、M4A 等音频后开始。', action: onImport)
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  itemCount: store.jobs.length,
                  itemBuilder: (context, i) => JobCard(job: store.jobs[i], compact: true),
                ),
        ),
      ]);
}

class PipelinePage extends StatelessWidget {
  const PipelinePage({super.key, required this.store});
  final AppStore store;
  static const stages = ['上传', '六轨', '分析', '和弦', '乐谱', '改编', '渲染', '入库'];

  @override
  Widget build(BuildContext context) => Column(children: [
        const PageHeader(title: '自动生产流水线', subtitle: '失败可续跑，任务状态自动保存'),
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
                        FilledButton.icon(
                          onPressed: job.isRunning ? null : () => unawaited(job.serverJobId.isEmpty ? store.startJob(job) : store.resumeJob(job)),
                          icon: Icon(job.serverJobId.isEmpty ? Icons.play_arrow : Icons.refresh),
                          label: Text(job.serverJobId.isEmpty ? '开始自动流水线' : (job.isDone ? '刷新结果' : '继续任务')),
                        ),
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
  final levels = <String, double>{'人声': .9, '鼓': .82, '贝斯': .8, '吉他': .84, '钢琴': .76, '其他': .65};
  static const notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

  PipelineJob? get selected {
    if (widget.store.jobs.isEmpty) return null;
    return widget.store.jobs.firstWhere((e) => e.id == selectedId, orElse: () => widget.store.jobs.first);
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
    final currentKey = transpose(job.originalKey, job.semitones);
    final capo = capoFor(currentKey);
    final artifactKey = {'和弦谱': 'lead_sheet', '五线谱': 'musicxml', '六线谱': 'guitar_tab', '贝斯谱': 'bass_score', '鼓谱': 'drum_score', '键盘谱': 'piano_score'}[scoreType];
    final artifact = job.artifacts[artifactKey];
    const trackKeys = {'人声': 'stem_vocals', '鼓': 'stem_drums', '贝斯': 'stem_bass', '吉他': 'stem_guitar', '钢琴': 'stem_piano', '其他': 'stem_other'};
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
        const Text('六轨混音', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        Card(child: Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Column(children: [
          for (final entry in levels.entries)
            ListTile(
              leading: Icon(entry.key == '鼓' ? Icons.album : Icons.multitrack_audio, color: accent),
              title: Text(entry.key),
              subtitle: Slider(value: entry.value, onChanged: (value) => setState(() => levels[entry.key] = value)),
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
          for (final type in const ['和弦谱', '五线谱', '六线谱', '贝斯谱', '鼓谱', '键盘谱'])
            ChoiceChip(label: Text(type), selected: scoreType == type, onSelected: (_) => setState(() => scoreType = type)),
        ]),
        const SizedBox(height: 10),
        Card(child: Padding(padding: const EdgeInsets.all(18), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(scoreType, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Text(artifact == null ? '流水线完成后，这里会显示服务器生成的$scoreType。' : '谱面已生成，可复制地址后打开或下载。', style: const TextStyle(color: Color(0xFFBDAAB5))),
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
              subtitle: Text(widget.store.jobs[i].isDone ? '六轨与谱面就绪' : widget.store.jobs[i].stage),
              trailing: IconButton(onPressed: () => setState(() => selectedId = widget.store.jobs[i].id), icon: const Icon(Icons.play_arrow)),
            ),
        ])),
      ])),
    ]);
  }
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
          Text('当前服务器：${widget.store.serverBase.isEmpty ? '未配置，请先到首页→设置填写' : widget.store.serverBase}', style: const TextStyle(color: Color(0xFFBDAAB5))),
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

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.store});
  final AppStore store;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late final TextEditingController server;
  late final TextEditingController token;

  @override
  void initState() {
    super.initState();
    server = TextEditingController(text: widget.store.serverBase);
    token = TextEditingController(text: widget.store.apiToken);
  }

  @override
  void dispose() {
    server.dispose();
    token.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        PageHeader(
          title: '设置',
          subtitle: '服务器、任务与版本',
          action: Navigator.of(context).canPop() ? IconButton(onPressed: () => Navigator.of(context).pop(), icon: const Icon(Icons.close)) : null,
        ),
        Expanded(child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 30), children: [
          Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('AI 服务器', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            TextField(controller: server, keyboardType: TextInputType.url, decoration: const InputDecoration(labelText: '服务器地址', hintText: '局域网：http://电脑IP:8000')),
            const SizedBox(height: 10),
            TextField(controller: token, obscureText: true, decoration: const InputDecoration(labelText: '访问令牌（可选）')),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: FilledButton(onPressed: () async {
                await widget.store.saveServer(server.text, token.text);
                if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('服务器设置已保存')));
              }, child: const Text('保存'))),
              const SizedBox(width: 10),
              Expanded(child: OutlinedButton(onPressed: () async {
                await widget.store.saveServer(server.text, token.text);
                await widget.store.testServer();
              }, child: const Text('测试连接'))),
            ]),
            const SizedBox(height: 10),
            Text('${widget.store.serverState} · ${widget.store.serverDetail}', style: TextStyle(color: widget.store.serverState == '在线' ? Colors.greenAccent : Colors.orangeAccent)),
            const SizedBox(height: 10),
            const Text(
              '同一 Wi-Fi：填写 http://电脑局域网IP:8000，例如 http://192.168.1.8:8000。外网使用已配置的 Cloudflare API 域名。手机不能填写 127.0.0.1 或 localhost。',
              style: TextStyle(color: Color(0xFFFFB36B), height: 1.45),
            ),
          ]))),
          const SizedBox(height: 12),
          const Card(child: Column(children: [
            ListTile(leading: Icon(Icons.security), title: Text('版权处理'), subtitle: Text('导入音频仅用于分析；最终输出使用新 MIDI 编配与音源重新渲染。')),
            Divider(height: 1),
            ListTile(leading: Icon(Icons.storage), title: Text('任务恢复'), subtitle: Text('歌曲、进度和服务器任务 ID 自动保存在本机。')),
            Divider(height: 1),
            ListTile(leading: Icon(Icons.info_outline), title: Text('版本'), subtitle: Text('$appName v$appVersion · Android / iOS 完整版')),
          ])),
          const SizedBox(height: 12),
          const Card(child: Padding(padding: EdgeInsets.all(16), child: Text(
            '服务器接口：健康检查、账号登录注册、内测群聊、上传任务、六轨/乐谱/MIDI 结果下载。移动端由 Windows/GPU 服务器执行 Demucs 与智能编配。',
            style: TextStyle(color: Color(0xFFBDAAB5)),
          ))),
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
