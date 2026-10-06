import 'dart:convert';
import 'package:http/http.dart' as http;

class XiaoHeApiService {
  // AI ထံသို့ စာသား ပေးပို့ပြီး တုံ့ပြန်ချက် ရယူခြင်း
  Future<Map<String, dynamic>> sendTextMessage(String text) async {
    try {
      final response = await http.post(
        Uri.parse('https://api.example.com/chat'), // မိမိ Backend URL ပြောင်းနိုင်ပါသည်
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'message': text}),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return {
          'text': data['replyText'] ?? '你好！我是小禾 (Hello! I am Xiao He).',
          'audioUrl': data['audioUrl'],
        };
      } else {
        return {
          'text': 'မက်ဆေ့ဂျ် ပေးပို့ရာတွင် အဆင်မပြေပါခင်ဗျာ။',
          'audioUrl': null,
        };
      }
    } catch (e) {
      // စမ်းသပ်မှုပြုလုပ်စဉ် API မရှိသေးပါက Demo တုံ့ပြန်မှု ပြပေးခြင်း
      return {
        'text': '你好！我是小禾 (Hello! I am Xiao He).',
        'audioUrl': null,
      };
    }
  }

  // အသံဖိုင် ပေးပို့ပြီး တုံ့ပြန်ချက် ရယူခြင်း
  Future<Map<String, dynamic>> sendAudioMessage(String audioPath) async {
    try {
      var request = http.MultipartRequest(
        'POST',
        Uri.parse('https://api.example.com/voice-chat'),
      );
      request.files.add(await http.MultipartFile.fromPath('audio', audioPath));

      var streamedResponse = await request.send();
      var response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return {
          'transcript': data['transcript'] ?? '',
          'replyText': data['replyText'] ?? '',
          'audioUrl': data['audioUrl'],
        };
      } else {
        return {
          'transcript': '',
          'replyText': 'အသံဖိုင် ပေးပို့၍ မရပါခင်ဗျာ။',
          'audioUrl': null,
        };
      }
    } catch (e) {
      return {
        'transcript': '你好',
        'replyText': '你好！很高兴认识你 (တွေ့ရတာ ဝမ်းသာပါတယ်)။',
        'audioUrl': null,
      };
    }
  }
}