/** This file contains startAudio and stopAudio functions that feed two-way audio over a WebSocket connection to a browser.
 * It is used by several examples. */

const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host; // Includes hostname and port if present

let audioWebsocket;
let mediaRecorder;

async function startAudio(path) {
    const wsUrl = `${protocol}//${host}${path}`;
    audioWebsocket = new WebSocket(wsUrl);

    // Initialize MediaRecorder to record the audio stream
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.onerror = (error) => console.error('MediaRecorder error:', error);
    mediaRecorder.ondataavailable = function(event) {
        if (event.data.size > 0 && audioWebsocket && audioWebsocket.readyState === WebSocket.OPEN) {
            audioWebsocket.send(event.data);
        }
    }

    // Initialize MediaSource to play back received audio
    const queue = [];
    let sourceBuffer;

    const mediaSource = new MediaSource();
    mediaSource.onsourceopen = () => {
        sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
        sourceBuffer.addEventListener('updateend', () => {
            if (queue.length > 0 && !sourceBuffer.updating) {
                sourceBuffer.appendBuffer(queue.shift());
            }
        });
        audioPlayer.play().catch(function(error) {
            if (error.name == "NotSupportedError") {
                console.log("Stopping playback.  No audio was received")
            }
        });
    };
    audioPlayer.src = URL.createObjectURL(mediaSource);
    audioWebsocket.onmessage = async (event) => {
        const audioData = await event.data.arrayBuffer();
        queue.push(audioData);
        if (sourceBuffer && !sourceBuffer.updating) {
            sourceBuffer.appendBuffer(queue.shift());
        }
    };
    audioWebsocket.onclose = () => {
        if (mediaSource.readyState === 'open') {
            mediaSource.endOfStream();
        }
    };
    audioWebsocket.onerror = (event) => {
        console.error('Audio WebSocket Error:', event);
    };
    audioWebsocket.onopen = function(event) {
        mediaRecorder.start(20); // Send data every 20ms.  This is what Twilio uses.
    };
}

function stopAudio() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
    if (audioWebsocket) {
        audioWebsocket.close();
    }
}

