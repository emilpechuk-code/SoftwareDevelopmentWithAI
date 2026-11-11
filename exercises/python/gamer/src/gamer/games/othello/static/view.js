const css = document.createElement("link");
css.rel = "stylesheet";
css.href = new URL("./view.css", import.meta.url).href;
document.head.append(css);

const title = (label) => label[0].toUpperCase() + label.slice(1);

export function render(container, envelope, { canMove, onMove }) {
  const { board, scores, legal_moves: legalMoves, last_pass: lastPass } = envelope.payload;
  const legal = new Set(canMove ? legalMoves.map((m) => `${m.row},${m.col}`) : []);
  const grid = document.createElement("div");
  grid.className = "othello-board";
  board.forEach((row, r) => row.forEach((cell, c) => {
    const square = document.createElement("button");
    square.className = "othello-cell";
    if (cell) {
      const disc = document.createElement("span");
      disc.className = `disc ${cell}`;
      square.append(disc);
    }
    if (legal.has(`${r},${c}`)) {
      square.classList.add("legal");
      square.addEventListener("click", () => onMove({ row: r, col: c }));
    } else {
      square.disabled = true;
    }
    grid.append(square);
  }));
  const info = document.createElement("p");
  info.textContent = `Black ${scores.black} – White ${scores.white}` + (lastPass ? ` · ${title(lastPass)} passed` : "");
  container.replaceChildren(info, grid);
}
