import 'package:flutter/material.dart';

import 'chat_screen.dart';


void main() {
  WidgetsFlutterBinding.ensureInitialized();

  runApp(
    const XiaoHeApp(),
  );
}


class XiaoHeApp
    extends StatelessWidget {
  const XiaoHeApp({super.key});


  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,

      title: '小禾',

      theme: ThemeData(
        useMaterial3: true,

        colorScheme:
            ColorScheme.fromSeed(
          seedColor:
              const Color(
            0xFF5F8E58,
          ),
        ),

        scaffoldBackgroundColor:
            const Color(
          0xFFF7F8FA,
        ),

        fontFamily: 'sans',
      ),

      home:
          const ChatScreen(),
    );
  }
}