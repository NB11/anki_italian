const sentencesInner = document.getElementById("sentences-inner");
const sentencesData = sentencesInner.innerHTML;
const sentencesPairs = sentencesData.split("\n\n");
shuffleArray(sentencesPairs);

let sentenceIndex = 0;

sentencesInner.ondblclick = () => {
  sentenceIndex = (sentenceIndex + 1) % sentencesPairs.length;
  render();
};

function render() {
  const sentencePair = sentencesPairs[sentenceIndex].split("\n");
  const it = processText(sentencePair[0], true);
  const de = processText(sentencePair[1], false, false);
  sentencesInner.innerHTML = `<div class="fr">${it}</div>`;

  (async () => {
    if (options.autoPlaySentence) {
      playAudio({ text: it });
    }
  })();

  const gameContainer = document.getElementById("cloze-game");
  gameContainer.innerHTML = "";
  gameContainer.className = "";
  initClozeGame({
    sentence: de,
    sentenceToRead: sentencePair[0],
    gameContainer,
    isGerman: true,
  });
}

render();

// Play the Italian word — autoplay on desktop, tap on mobile
const wordEl = document.querySelector('.word');
if (wordEl) {
  const playWord = () => playAudio({ text: wordEl.textContent.trim() });
  wordEl.style.cursor = 'pointer';
  wordEl.onclick = playWord;
  playWord();
}
