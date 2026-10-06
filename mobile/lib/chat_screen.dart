import 'dart:io';
import 'package:flutter/material.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'api_service.dart';

enum MessageSender { user, xiaoHe }

class ChatMessage {
  final MessageSender sender;
  final String text;
  final String? audioUrl;

  ChatMessage({
    required this.sender,
    required this.text,
    this.audioUrl,
  });
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final List<ChatMessage> _messages = [];
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final XiaoHeApiService _apiService = XiaoHeApiService();
  final AudioPlayer _audioPlayer = AudioPlayer();
  final AudioRecorder _audioRecorder = AudioRecorder();

  bool _isRecording = false;
  bool _isLoading = false;
  String? _currentlyPlayingUrl;

  @override
  void initState() {
    super.initState();
    // နှုတ်ခွန်းဆက် မက်ဆေ့ဂျ် အစဦး ထည့်သွင်းခြင်း
    _messages.add(
      ChatMessage(
        sender: MessageSender.xiaoHe,
        text: '你好！我是你的中文陪练小禾。你想聊点什么？\n(မင်္ဂလာပါ! ကျွန်မကတော့ တရုတ်စာ လေ့ကျင့်ပေးမယ့် Xiao He ဖြစ်ပါတယ်။ ဘာအကြောင်း ပြောချင်ပါသလဲ?)',
      ),
    );
  }

  @override
  void dispose() {
    _audioPlayer.dispose();
    _audioRecorder.dispose();
    _textController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // စာသား ပေးပို့ခြင်း
  Future<void> _sendText() async {
    final text = _textController.text.trim();
    if (text.isEmpty) return;

    _textController.clear();
    setState(() {
      _messages.add(ChatMessage(sender: MessageSender.user, text: text));
      _isLoading = true;
    });
    _scrollToBottom();

    final response = await _apiService.sendTextMessage(text);

    setState(() {
      _isLoading = false;
      _messages.add(
        ChatMessage(
          sender: MessageSender.xiaoHe,
          text: response['text'] ?? '',
          audioUrl: response['audioUrl'],
        ),
      );
    });
    _scrollToBottom();

    if (response['audioUrl'] != null) {
      _playAudio(response['audioUrl']);
    }
  }

  // အသံဖမ်းယူမှု စတင်ခြင်း
  Future<void> _startRecording() async {
    try {
      if (await _audioRecorder.hasPermission()) {
        final dir = await getTemporaryDirectory();
        final path = '${dir.path}/temp_voice.m4a';

        await _audioRecorder.start(
          const RecordConfig(encoder: AudioEncoder.aacLc),
          path: path,
        );

        setState(() {
          _isRecording = true;
        });
      }
    } catch (e) {
      debugPrint('Error starting record: $e');
    }
  }

  // အသံဖမ်းယူမှု ရပ်တန့်ပြီး ပေးပို့ခြင်း
  Future<void> _stopRecording() async {
    try {
      final path = await _audioRecorder.stop();
      setState(() {
        _isRecording = false;
      });

      if (path != null) {
        setState(() {
          _isLoading = true;
        });

        final response = await _apiService.sendAudioMessage(path);

        setState(() {
          _isLoading = false;
          if (response['transcript'] != null && response['transcript'].isNotEmpty) {
            _messages.add(
              ChatMessage(sender: MessageSender.user, text: response['transcript']),
            );
          }
          _messages.add(
            ChatMessage(
              sender: MessageSender.xiaoHe,
              text: response['replyText'] ?? '',
              audioUrl: response['audioUrl'],
            ),
          );
        });
        _scrollToBottom();

        if (response['audioUrl'] != null) {
          _playAudio(response['audioUrl']);
        }
      }
    } catch (e) {
      debugPrint('Error stopping record: $e');
    }
  }

  // အသံပြန်ဖွင့်ခြင်း
  Future<void> _playAudio(String url) async {
    if (_currentlyPlayingUrl == url) {
      await _audioPlayer.stop();
      setState(() {
        _currentlyPlayingUrl = null;
      });
    } else {
      await _audioPlayer.stop();
      await _audioPlayer.play(UrlSource(url));
      setState(() {
        _currentlyPlayingUrl = url;
      });

      _audioPlayer.onPlayerComplete.listen((_) {
        if (mounted) {
          setState(() {
            _currentlyPlayingUrl = null;
          });
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            CircleAvatar(
              backgroundColor: Colors.teal,
              child: Text('小', style: TextStyle(color: Colors.white)),
            ),
            SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('小禾 (Xiao He)', style: TextStyle(fontSize: 16)),
                Text('在线 · 中文陪练', style: TextStyle(fontSize: 12, color: Colors.grey)),
              ],
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.all(12),
              itemCount: _messages.length + (_isLoading ? 1 : 0),
              itemBuilder: (context, index) {
                if (index == _messages.length && _isLoading) {
                  return const Padding(
                    padding: EdgeInsets.symmetric(vertical: 8.0),
                    child: Row(
                      children: [
                        CircularProgressIndicator(strokeWidth: 2),
                        SizedBox(width: 10),
                        Text('小禾正在输入… (Xiao He ရေးနေပါသည်...)'),
                      ],
                    ),
                  );
                }

                final message = _messages[index];
                final isUser = message.sender == MessageSender.user;

                return Align(
                  alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
                  child: Container(
                    margin: const EdgeInsets.symmetric(vertical: 6),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: isUser ? Colors.teal.shade100 : Colors.grey.shade200,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Flexible(
                          child: Text(
                            message.text,
                            style: const TextStyle(fontSize: 15),
                          ),
                        ),
                        if (message.audioUrl != null) ...[
                          const SizedBox(width: 8),
                          IconButton(
                            icon: Icon(
                              _currentlyPlayingUrl == message.audioUrl
                                  ? Icons.stop_circle
                                  : Icons.volume_up,
                            ),
                            onPressed: () => _playAudio(message.audioUrl!),
                          ),
                        ],
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
          Container(
            padding: const EdgeInsets.all(8),
            color: Colors.white,
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _textController,
                    decoration: const InputDecoration(
                      hintText: 'စာရိုက်ပါ သို့မဟုတ် မိုက်ကိုဖိထားပါ...',
                      border: OutlineInputBorder(),
                      contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    ),
                    onSubmitted: (_) => _sendText(),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.send, color: Colors.teal),
                  onPressed: _sendText,
                ),
                GestureDetector(
                  onLongPress: _startRecording,
                  onLongPressUp: _stopRecording,
                  child: Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: _isRecording ? Colors.red : Colors.teal,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      _isRecording ? Icons.mic : Icons.mic_none,
                      color: Colors.white,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}