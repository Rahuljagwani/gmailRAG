/**
 * Grove | HR Reply Assistant (Gmail Add-on, Commit 8: wired to backend)
 *
 * Contextual trigger renders a preview of the open email with a "Draft reply with Grove"
 * button. The button POSTs the email to the FastAPI /answer backend and renders the
 * grounded draft, citation chips, and a warning banner when the documents don't clearly
 * answer the question. (Commit 9 adds an editable field + insert-into-reply.)
 */

/**
 * Entry point declared in appsscript.json (gmail.contextualTriggers.onTriggerFunction).
 * @param {Object} e Gmail add-on event; e.gmail has messageId + a scoped accessToken.
 * @return {Card[]} the card(s) to render in the sidebar.
 */
function onGmailMessageOpen(e) {
  var msg = readOpenMessage(e);
  var preview = truncate(msg.body, 400);

  var section = CardService.newCardSection()
    .addWidget(
      CardService.newDecoratedText().setTopLabel('From').setText(msg.from).setWrapText(true)
    )
    .addWidget(
      CardService.newDecoratedText()
        .setTopLabel('Subject')
        .setText(msg.subject)
        .setWrapText(true)
    )
    .addWidget(CardService.newTextParagraph().setText('<b>Email preview</b>'))
    .addWidget(CardService.newTextParagraph().setText(escapeHtml(preview)))
    .addWidget(
      CardService.newTextButton()
        .setText('Draft reply with Grove')
        .setTextButtonStyle(CardService.TextButtonStyle.FILLED)
        .setOnClickAction(CardService.newAction().setFunctionName('onDraftReply'))
    );

  return [
    CardService.newCardBuilder()
      .setHeader(
        CardService.newCardHeader()
          .setTitle('Grove')
          .setSubtitle('HR reply assistant · grounded in the plan documents')
      )
      .addSection(section)
      .build()
  ];
}

/**
 * Button handler: call the backend and push a card with the grounded draft.
 * @param {Object} e Gmail add-on action event (carries e.gmail context).
 * @return {ActionResponse}
 */
function onDraftReply(e) {
  var msg = readOpenMessage(e);
  var card;
  try {
    var result = callAnswerBackend_(msg.subject, msg.body);
    card = buildAnswerCard_(result);
  } catch (err) {
    card = buildErrorCard_(err.message);
  }
  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().pushCard(card))
    .build();
}

/** Builds the card that shows the grounded draft + citations (+ warning if unsupported). */
function buildAnswerCard_(result) {
  var builder = CardService.newCardBuilder().setHeader(
    CardService.newCardHeader().setTitle('Grove').setSubtitle('Suggested reply')
  );

  if (!result.has_clear_answer) {
    builder.addSection(
      CardService.newCardSection().addWidget(
        CardService.newTextParagraph().setText(
          '<b><font color="#b00020">⚠ The documents don\'t clearly answer this.</font></b> ' +
            'Review carefully before sending. Grove has flagged that part as unsupported.'
        )
      )
    );
  }

  builder.addSection(
    CardService.newCardSection()
      .setHeader('Draft')
      .addWidget(CardService.newTextParagraph().setText(mdToCardHtml_(result.answer || '')))
  );

  var citations = result.citations || [];
  if (citations.length) {
    var citeSection = CardService.newCardSection().setHeader(
      'Sources (' + citations.length + ')'
    );
    for (var i = 0; i < citations.length; i++) {
      var c = citations[i];
      var label = c.doc + ' · ' + (c.section || '') + (c.page ? ' (p' + c.page + ')' : '');
      citeSection.addWidget(
        CardService.newDecoratedText()
          .setTopLabel(label)
          .setText(escapeHtml(truncate(c.quote || '', 220)))
          .setWrapText(true)
      );
    }
    builder.addSection(citeSection);
  }

  builder.addSection(
    CardService.newCardSection().addWidget(
      CardService.newTextButton()
        .setText('Regenerate')
        .setOnClickAction(CardService.newAction().setFunctionName('onDraftReply'))
    )
  );

  return builder.build();
}

/** Builds a simple error card with a retry button. */
function buildErrorCard_(message) {
  return CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('Grove').setSubtitle('Something went wrong'))
    .addSection(
      CardService.newCardSection()
        .addWidget(
          CardService.newTextParagraph().setText(
            '<font color="#b00020">' + escapeHtml(message) + '</font>'
          )
        )
        .addWidget(
          CardService.newTextButton()
            .setText('Try again')
            .setOnClickAction(CardService.newAction().setFunctionName('onDraftReply'))
        )
    )
    .build();
}

/**
 * Reads the currently open Gmail message using the add-on's scoped access token.
 * @param {Object} e the Gmail add-on event.
 * @return {{subject: string, from: string, body: string}}
 */
function readOpenMessage(e) {
  GmailApp.setCurrentMessageAccessToken(e.gmail.accessToken);
  var message = GmailApp.getMessageById(e.gmail.messageId);
  return {
    subject: message.getSubject() || '(no subject)',
    from: message.getFrom() || '(unknown sender)',
    body: message.getPlainBody() || ''
  };
}

/** Trims text to a max length with an ellipsis. */
function truncate(text, max) {
  if (!text) return '';
  return text.length > max ? text.substring(0, max) + '…' : text;
}

/** Minimal HTML escaping for the limited widget markup Gmail cards allow. */
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** Converts the model's light markdown (**bold**, newlines) to Gmail-card HTML. */
function mdToCardHtml_(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/\n/g, '<br>');
}
