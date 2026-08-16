import 'dart:convert';
import 'dart:io';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

void main() => runApp(const DongbaMusicApp());

class DongbaMusicApp extends StatelessWidget {
  const DongbaMusicApp({super.key});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFFD7A63A);
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: '东巴音乐',
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.dark),
        scaffoldBackgroundColor: const Color(0xFF07101D),
        cardColor: const Color(0xFF101C2D),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int index = 0;
  String serverState = '未检测';
  String gpu = '—';
  String? selectedFile;
  int semitones = 0;
  String originalKey = 'D';
  bool busy = false;

  static const apiBase = 'https://api.db0888.com';
  static const notes = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];

  @override
  void initState() {
    super.initState();
    checkServer();
  }

  String get currentKey {
    final i = notes.indexOf(originalKey);
    if (i < 0) return originalKey;
    return notes[(i + semitones) % 12 < 0 ? (i + semitones) % 12 + 12 : (i + semitones) % 12];
  }

  int get capoSuggestion {
    final target = notes.indexOf(currentKey);
    const easyRoots = ['C','G','D','A','E'];
    int best = 0;
    int bestScore = 99;
    for (int capo = 0; capo <= 7; capo++) {
      final sounding = (target - capo) % 12;
      final shape = notes[sounding < 0 ? sounding + 12 : sounding];
      final score = easyRoots.contains(shape) ? capo : capo + 20;
      if (score < bestScore) { bestScore = score; best = capo; }
    }
    return best;
  }

  Future<void> checkServer() async {
    setState(() { serverState = '检测中…'; });
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
      final req = await client.getUrl(Uri.parse('$apiBase/health'));
      final res = await req.close();
      final body = await res.transform(utf8.decoder).join();
      client.close(force: true);
      final data = jsonDecode(body) as Map<String, dynamic>;
      setState(() {
        serverState = res.statusCode == 200 ? '在线' : '异常 ${res.statusCode}';
        gpu = '${data['gpu'] ?? '—'}';
      });
    } catch (e) {
      setState(() { serverState = '离线'; gpu = '—'; });
    }
  }

  Future<void> pickAudio() async {
    final r = await FilePicker.platform.pickFiles(type: FileType.audio, allowMultiple: false);
    if (r != null && r.files.isNotEmpty) {
      setState(() => selectedFile = r.files.single.name);
    }
  }

  void changeTranspose(int delta) {
    setState(() {
      semitones = (semitones + delta).clamp(-12, 12);
    });
  }

  Widget statusCard() => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Row(children: [
        Container(width: 12, height: 12, decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: serverState == '在线' ? Colors.greenAccent : Colors.orangeAccent,
        )),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('东巴音乐 AI Server · $serverState', style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(gpu, style: TextStyle(color: Colors.white.withOpacity(.65), fontSize: 12)),
        ])),
        IconButton(onPressed: checkServer, icon: const Icon(Icons.refresh)),
      ]),
    ),
  );

  Widget dashboard() => ListView(padding: const EdgeInsets.all(16), children: [
    Row(children: [
      ClipRRect(borderRadius: BorderRadius.circular(18), child: Image.asset('assets/dongba_icon.png', width: 72, height: 72, fit: BoxFit.cover)),
      const SizedBox(width: 14),
      const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('东巴音乐', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800)),
        SizedBox(height: 3),
        Text('AI 分轨 · 乐手演奏 · 智能谱面', style: TextStyle(color: Color(0xFF9CB0CC))),
      ])),
    ]),
    const SizedBox(height: 18),
    statusCard(),
    const SizedBox(height: 12),
    Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Text('导入音乐', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
      const SizedBox(height: 10),
      Text(selectedFile ?? '尚未选择歌曲', maxLines: 2, overflow: TextOverflow.ellipsis),
      const SizedBox(height: 12),
      FilledButton.icon(onPressed: pickAudio, icon: const Icon(Icons.library_music), label: const Text('选择手机里的音乐')),
      const SizedBox(height: 8),
      OutlinedButton.icon(onPressed: selectedFile == null ? null : () => setState(() => busy = true), icon: const Icon(Icons.auto_awesome), label: const Text('提交六轨任务（服务器接口待接入）')),
      if (busy) const Padding(padding: EdgeInsets.only(top: 10), child: Text('当前测试版先验证手机 UI、文件选择和服务器连通性。')),
    ]))),
    const SizedBox(height: 12),
    const Row(children: [
      Expanded(child: _Feature(icon: Icons.graphic_eq, title: '六轨分离', sub: '人声 / 鼓 / 贝斯 / 吉他 / 钢琴 / 其他')),
      SizedBox(width: 10),
      Expanded(child: _Feature(icon: Icons.queue_music, title: '演出谱面', sub: 'TAB / 五线谱 / 鼓谱 / 键盘谱')),
    ]),
  ]);

  Widget musicPage() => ListView(padding: const EdgeInsets.all(16), children: [
    const Text('音乐工作台', style: TextStyle(fontSize: 25, fontWeight: FontWeight.w800)),
    const SizedBox(height: 12), statusCard(), const SizedBox(height: 12),
    Card(child: ListTile(
      leading: const CircleAvatar(child: Icon(Icons.music_note)),
      title: Text(selectedFile ?? '未导入歌曲'),
      subtitle: const Text('手机测试版 · 本地选择后由家庭 GPU Server 处理'),
      trailing: IconButton(onPressed: pickAudio, icon: const Icon(Icons.add)),
    )),
    const SizedBox(height: 10),
    for (final x in const [('人声','Vocals'),('鼓','Drums'),('贝斯','Bass'),('吉他','Guitar'),('钢琴','Piano'),('其他','Other')])
      Card(child: ListTile(leading: const Icon(Icons.multitrack_audio), title: Text(x.$1), subtitle: Text(x.$2), trailing: const Icon(Icons.lock_clock))),
  ]);

  Widget performancePage() => ListView(padding: const EdgeInsets.all(16), children: [
    const Text('现场演奏', style: TextStyle(fontSize: 25, fontWeight: FontWeight.w800)),
    const SizedBox(height: 12),
    Card(child: Padding(padding: const EdgeInsets.all(18), child: Column(children: [
      Text('原调 $originalKey', style: TextStyle(color: Colors.white.withOpacity(.65))),
      const SizedBox(height: 4),
      Text(currentKey, style: const TextStyle(fontSize: 58, fontWeight: FontWeight.w900)),
      Text('${semitones >= 0 ? '+' : ''}$semitones 半音', style: const TextStyle(color: Color(0xFFD7A63A), fontWeight: FontWeight.w700)),
      const SizedBox(height: 16),
      Row(children: [
        Expanded(child: FilledButton.tonalIcon(onPressed: () => changeTranspose(-1), icon: const Icon(Icons.keyboard_arrow_down), label: const Text('降半音'))),
        const SizedBox(width: 10),
        Expanded(child: FilledButton.tonalIcon(onPressed: () => changeTranspose(1), icon: const Icon(Icons.keyboard_arrow_up), label: const Text('升半音'))),
      ]),
      const SizedBox(height: 8),
      TextButton(onPressed: () => setState(() => semitones = 0), child: const Text('恢复原调')),
    ]))),
    const SizedBox(height: 12),
    Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('吉他', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18)),
      const SizedBox(height: 8),
      Text('建议变调夹：第 $capoSuggestion 品'),
      const Text('谱型：六线谱 TAB / 五线谱 / 和弦谱（可切换）'),
    ]))),
    const SizedBox(height: 10),
    for (final e in const [('吉他','六线谱 TAB'),('贝斯','Bass TAB / 五线谱'),('鼓','标准鼓谱'),('钢琴','高低音大谱表'),('主唱','歌词 / 和弦 / 进歌提示')])
      Card(child: ListTile(title: Text(e.$1), subtitle: Text(e.$2), trailing: const Icon(Icons.chevron_right))),
  ]);

  Widget settingsPage() => ListView(padding: const EdgeInsets.all(16), children: [
    const Text('设置', style: TextStyle(fontSize: 25, fontWeight: FontWeight.w800)),
    const SizedBox(height: 12),
    Card(child: ListTile(title: const Text('服务器'), subtitle: const Text(apiBase), trailing: Text(serverState))),
    const Card(child: ListTile(title: Text('分离模式'), subtitle: Text('演出级高质量：人声精分 → 乐器二次分离'))),
    const Card(child: ListTile(title: Text('版本'), subtitle: Text('Mobile Test v0.1.0'))),
  ]);

  @override
  Widget build(BuildContext context) {
    final pages = [dashboard(), musicPage(), performancePage(), settingsPage()];
    return Scaffold(
      body: SafeArea(child: pages[index]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (v) => setState(() => index = v),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: '首页'),
          NavigationDestination(icon: Icon(Icons.library_music_outlined), selectedIcon: Icon(Icons.library_music), label: '音乐'),
          NavigationDestination(icon: Icon(Icons.piano_outlined), selectedIcon: Icon(Icons.piano), label: '演出'),
          NavigationDestination(icon: Icon(Icons.settings_outlined), selectedIcon: Icon(Icons.settings), label: '设置'),
        ],
      ),
    );
  }
}

class _Feature extends StatelessWidget {
  final IconData icon; final String title; final String sub;
  const _Feature({required this.icon, required this.title, required this.sub});
  @override
  Widget build(BuildContext context) => Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Icon(icon, size: 30, color: Theme.of(context).colorScheme.primary),
    const SizedBox(height: 10), Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
    const SizedBox(height: 4), Text(sub, style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(.62))),
  ])));
}
