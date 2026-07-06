/**
 * Grove | HR Reply Assistant (Gmail Add-on)
 *
 * When an email is opened, Grove POSTs it to the FastAPI /answer backend and renders the
 * grounded draft directly (no extra click): citation chips, a warning banner when the
 * documents don't clearly answer, an editable draft field, and an "Insert into reply"
 * compose action.
 */

/**
 * Entry point declared in appsscript.json (gmail.contextualTriggers.onTriggerFunction).
 * Generates the draft immediately on open.
 * @param {Object} e Gmail add-on event; e.gmail has messageId + a scoped accessToken.
 * @return {Card[]}
 */
function onGmailMessageOpen(e) {
  return [buildDraftCardForMessage_(e)];
}

/**
 * Regenerate handler: rebuild the draft card in place.
 * @param {Object} e Gmail add-on action event.
 * @return {ActionResponse}
 */
function onRegenerate(e) {
  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().updateCard(buildDraftCardForMessage_(e)))
    .build();
}

/** Reads the open message, calls the backend, and returns an answer card (or error card). */
function buildDraftCardForMessage_(e) {
  try {
    var msg = readOpenMessage(e);
    var result = callAnswerBackend_(msg.subject, msg.body, firstNameFromSender_(msg.from));
    return buildAnswerCard_(result);
  } catch (err) {
    return buildErrorCard_(err.message);
  }
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
      .setHeader('Draft (editable)')
      .addWidget(
        CardService.newTextInput()
          .setFieldName('draft')
          .setTitle('Edit before inserting')
          .setMultiline(true)
          .setValue(mdToPlainText_(result.answer || ''))
      )
  );

  var buttons = CardService.newButtonSet()
    .addButton(
      CardService.newTextButton()
        .setText('Insert into reply')
        .setTextButtonStyle(CardService.TextButtonStyle.FILLED)
        .setComposeAction(
          CardService.newAction().setFunctionName('onInsertReply'),
          CardService.ComposedEmailType.REPLY_AS_DRAFT
        )
    )
    .addButton(
      CardService.newTextButton()
        .setText('Regenerate')
        .setOnClickAction(CardService.newAction().setFunctionName('onRegenerate'))
    );
  builder.addSection(CardService.newCardSection().addWidget(buttons));

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

  return builder.build();
}

/**
 * Compose action: create a Gmail draft reply pre-filled with the (edited) draft text.
 * @param {Object} e action event; e.formInput.draft holds the edited text.
 * @return {ComposeActionResponse}
 */
function onInsertReply(e) {
  var draftText = (e.formInput && e.formInput.draft) || '';
  GmailApp.setCurrentMessageAccessToken(e.gmail.accessToken);
  var message = GmailApp.getMessageById(e.gmail.messageId);
  var draft = message.createDraftReply(draftText);
  return CardService.newComposeActionResponseBuilder().setGmailDraft(draft).build();
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

/** Strips markdown markers so the editable draft / inserted reply is clean plain text. */
function mdToPlainText_(text) {
  return String(text).replace(/\*\*(.+?)\*\*/g, '$1');
}

/**
 * Extracts a likely first name from a Gmail "From" header like
 * "Jane Doe <jane@x.com>" -> "Jane". Returns '' if it looks like a non-personal sender
 * (e.g. "GSoC Program Admins", "no-reply"), so the backend falls back to "Hi there,".
 */
function firstNameFromSender_(from) {
  if (!from) return '';
  var name = from.split('<')[0].trim().replace(/^"|"$/g, '');
  if (!name || /no-?reply|team|admin|support|notification/i.test(name)) return '';
  var first = name.split(/\s+/)[0];
  // only treat as a name if it's alphabetic and not an org-ish all-caps acronym
  if (!/^[A-Za-z][A-Za-z'.-]*$/.test(first)) return '';
  return first;
}
