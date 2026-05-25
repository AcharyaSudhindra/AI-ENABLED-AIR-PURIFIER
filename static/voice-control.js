(function() {
  const btn = document.getElementById('voiceBtn');
  const toast = document.getElementById('voiceToast');
  
  if (!btn || !toast) return;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    btn.style.display = 'none';
    console.warn("Speech Recognition API is not supported in this browser.");
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.lang = 'en-US';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  let isListening = false;
  let toastTimeout = null;
  let forceStop = false;

  function showToast(msg, duration = 3000) {
    toast.textContent = msg;
    toast.classList.add('show');
    if (toastTimeout) clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => {
      toast.classList.remove('show');
    }, duration);
  }

  btn.addEventListener('click', () => {
    if (isListening) {
      forceStop = true;
      recognition.stop();
      isListening = false;
      btn.classList.remove('listening');
      showToast("Voice Control Disabled");
    } else {
      try {
        forceStop = false;
        recognition.start();
        isListening = true;
        btn.classList.add('listening');
        showToast("Voice Control Active! Say 'AirGuard...'", 5000);
      } catch (e) {
        showToast("Error starting microphone");
      }
    }
  });

  recognition.onresult = function(event) {
    // Because it's continuous, we loop through all new results
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        const transcript = event.results[i][0].transcript.toLowerCase().trim();
        
        // Check for the Wake Word
        if (transcript.includes("airguard") || transcript.includes("air guard")) {
          // Extract everything after the wake word
          let cmd = transcript.split(/air\s?guard/)[1].trim();
          if (cmd) {
            showToast(`Heard: "${cmd}"`, 4000);
            processCommand(cmd);
          } else {
            showToast("AirGuard is listening...");
            speakText("Yes, I'm listening. How can I help?");
          }
        }
      }
    }
  };

  recognition.onspeechend = function() {
    // Do nothing, keep listening because continuous = true
  };

  recognition.onend = function() {
    // If not manually stopped, restart the engine (Always-on logic)
    if (!forceStop) {
      try {
        recognition.start();
      } catch(e) {
        isListening = false;
        btn.classList.remove('listening');
      }
    }
  };

  recognition.onerror = function(event) {
    if (event.error === 'not-allowed') {
      forceStop = true;
      isListening = false;
      btn.classList.remove('listening');
      showToast(`Microphone Access Denied`);
    }
    // 'no-speech' is common, we just let it restart via onend
  };

  let voices = [];
  function loadVoices() {
    voices = window.speechSynthesis.getVoices();
  }
  if ('speechSynthesis' in window) {
    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;
  }

  function speakText(text) {
    if ('speechSynthesis' in window) {
      const msg = new SpeechSynthesisUtterance(text);
      const naturalVoice = voices.find(v => 
        v.name.includes('Google UK English Female') || 
        v.name.includes('Samantha') || 
        v.name.includes('Zira') || 
        v.name.includes('Natural')
      );
      if (naturalVoice) {
        msg.voice = naturalVoice;
      }
      window.speechSynthesis.speak(msg);
    }
  }

  function processCommand(cmd) {
    // Fan controls
    if (cmd.includes("turn on the fan") || cmd.includes("turn fan on") || cmd.includes("fan on")) {
      sendCommand('/api/fan', { on: true }, "Fan turned ON");
      speakText("Turning the fan on.");
    } else if (cmd.includes("turn off the fan") || cmd.includes("turn fan off") || cmd.includes("fan off")) {
      sendCommand('/api/fan', { on: false }, "Fan turned OFF");
      speakText("Turning the fan off.");
    } 
    // Mode controls
    else if (cmd.includes("auto mode") || cmd.includes("automatic")) {
      sendCommand('/api/settings', { mode: 'auto' }, "Switched to Auto Mode");
      speakText("Switching to automatic mode.");
    } else if (cmd.includes("manual mode") || cmd.includes("manual")) {
      sendCommand('/api/settings', { mode: 'manual' }, "Switched to Manual Mode");
      speakText("Switching to manual mode.");
    }
    // Questions: Air Quality
    else if (cmd.includes("air quality") || cmd.includes("how is the air") || cmd.includes("aqi") || cmd.includes("pollution")) {
      const aqiEl = document.getElementById('aqi');
      if (aqiEl && aqiEl.textContent !== '--') {
        let val = Number(aqiEl.textContent);
        let label = "Good";
        if (val > 300) label = "Hazardous";
        else if (val > 200) label = "Very Unhealthy";
        else if (val > 150) label = "Unhealthy";
        else if (val > 100) label = "Unhealthy for Sensitive Groups";
        else if (val > 50) label = "Moderate";
        speakText(`The current air quality index is ${val}, which is considered ${label}.`);
      } else {
        speakText("I cannot read the air quality right now.");
      }
    }
    // Questions: Temperature
    else if (cmd.includes("temperature") || cmd.includes("how hot") || cmd.includes("how cold")) {
      const tempEl = document.getElementById('temp');
      if (tempEl && tempEl.textContent !== '--') {
        speakText(`The current temperature is ${tempEl.textContent} degrees Celsius.`);
      } else {
        speakText("I don't have the temperature data at the moment.");
      }
    }
    // Questions: Humidity
    else if (cmd.includes("humidity") || cmd.includes("how humid")) {
      const humEl = document.getElementById('hum');
      if (humEl && humEl.textContent !== '--') {
        speakText(`The indoor humidity is at ${humEl.textContent} percent.`);
      } else {
        speakText("I cannot read the humidity right now.");
      }
    }
    // Questions: Mode
    else if (cmd.includes("what mode") || cmd.includes("current mode")) {
      const modeEl = document.getElementById('mode');
      if (modeEl && modeEl.textContent.includes('AUTO')) {
        speakText("I am currently running in Auto Mode.");
      } else if (modeEl && modeEl.textContent.includes('MANUAL')) {
        speakText("I am currently running in Manual Mode.");
      } else {
        speakText("I'm not sure what mode I'm in.");
      }
    }
    // Questions: Status
    else if (cmd.includes("status") || cmd.includes("online")) {
      const conn = document.getElementById('connLabel');
      if (conn) {
        speakText(`My current connection status is: ${conn.textContent}.`);
      }
    }
    else {
      showToast("Command not recognized.");
      speakText("I heard you say AirGuard, but I didn't recognize that command.");
    }
  }

  function sendCommand(endpoint, payload, successMsg) {
    fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(data => {
      showToast(successMsg);
      if (typeof renderLive === 'function') {
        renderLive(data);
      }
    })
    .catch(err => {
      showToast("Error executing command");
      console.error(err);
    });
  }

})();
