# 🤖 XiaoZhi AI Assistant (Integrated Module)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Original Project](https://img.shields.io/badge/Original_Project-78%2Fxiaozhi--esp32-blue)](https://github.com/78/xiaozhi-esp32)

> **Important Notice:** This directory contains the open-source **XiaoZhi AI Chatbot** project, which has been integrated into the AI-Based Air Purifier ecosystem. All original copyrights, trademarks, and licenses belong to the respective authors of the `xiaozhi-esp32` project.

---

## 🌟 Overview

As a voice interaction entry point, the XiaoZhi AI chatbot leverages the capabilities of large language models (like Qwen / DeepSeek) and achieves multi-terminal control via the MCP protocol. In the context of this repository, it serves as the intelligent brain and voice-interface for controlling smart devices.

## ✨ Key Features

- **Connectivity:** Wi-Fi / ML307 Cat.1 4G
- **Voice Capabilities:** Offline voice wake-up via [ESP-SR](https://github.com/espressif/esp-sr)
- **Architecture:** Voice interaction based on a streaming ASR + LLM + TTS architecture using OPUS audio codec.
- **Hardware Control:** Device-side MCP for hardware components (Speaker, LED, Servo, GPIO, etc.)
- **Advanced Integrations:** Cloud-side MCP for smart home control, knowledge search, and more.
- **Displays:** OLED / LCD display support with emoji rendering.

## 🔗 Original Project & Documentation

This module is directly based on the fantastic work done by the XiaoZhi AI open-source community. For full documentation, hardware support, firmware flashing guides, and the latest updates, please visit the original repository:

- **Original Repository:** [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)
- **Official Website:** [xiaozhi.me](https://xiaozhi.me)

## 🛠️ Developer Resources

If you are looking to develop or modify this component, please refer to the original developer guides included in this folder:
- [Custom Board Guide](docs/custom-board.md)
- [MCP Protocol IoT Control Usage](docs/mcp-usage.md)
- [MCP Protocol Interaction Flow](docs/mcp-protocol.md)
- [WebSocket Communication Protocol](docs/websocket.md)

## 📜 License

This component is distributed under the **MIT License**.

It allows anyone to use it for free, including for commercial purposes, provided the original copyright notices are retained. We extend our deepest gratitude to the creators and maintainers of the `xiaozhi-esp32` project for making this integration possible!

For detailed license information, please see the [LICENSE](LICENSE) file located in this directory.

---
*If you have any questions specific to the core chatbot functionality, please refer to the original repository's issue tracker or their community Discord.*