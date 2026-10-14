const fs = require('fs');

const source = fs.readFileSync('background.js', 'utf8');
const handlerStart = source.indexOf("if (message.command !== 'send' && message.command !== 'send-wakeback')");
const handlerEnd = source.indexOf("} catch (error)", handlerStart);
if (handlerStart < 0 || handlerEnd <= handlerStart) {
  throw new Error('native send/send-wakeback dispatch handler missing');
}

const handler = source.slice(handlerStart, handlerEnd);
if (!handler.includes("returnToRole: String(message.returnTo || '').trim()")) {
  throw new Error('send-wakeback does not forward the caller-provided exact return role');
}
if (handler.includes("returnToRole: message.command === 'send-wakeback' ? 'WORKER'")) {
  throw new Error('send-wakeback still rewrites the exact manager role to WORKER');
}
console.log('native wakeback exact-manager routing fence PASS');
