const defaults={includeOriginals:true,extractArchives:true,includeCards:true,includeSignatures:true,includeScreenshots:true,autoRegister:true,runAnomalyScan:true};
let settings={...defaults};
let csrfToken="";
let selectedFiles=[];
let statusCache=null;
let anomalyReport=null;
let findingLimit=100;
let documentTree=null;
let treeStatus="all";
let contactsCache=[];
let selectedContactId=null;
let contactContext={cases:[],proceedings:[],roles:[]};

const $=selector=>document.querySelector(selector);
const $$=selector=>[...document.querySelectorAll(selector)];
const severityLabels={critical:"Критичний",high:"Високий",medium:"Середній",low:"Низький",info:"Інформація"};
const confidenceLabels={high:"висока",medium:"середня",low:"низька"};
const statusLabels={open:"Відкрито",acknowledged:"Взято до уваги",resolved:"Пояснено/усунуто",false_positive:"Хибний сигнал"};
const treeStatusLabels={completed:"Завершено",in_progress:"В роботі",waiting:"Очікує",needs_review:"Потребує перевірки"};
const treeStatusOptions=current=>Object.entries(treeStatusLabels).map(([value,label])=>`<option value="${value}" ${value===current?"selected":""}>${escapeHtml(label)}</option>`).join("");

const formatBytes=value=>{if(!value)return"0 Б";const units=["Б","КБ","МБ","ГБ"];const i=Math.min(Math.floor(Math.log(value)/Math.log(1024)),3);return`${(value/1024**i).toFixed(i?1:0)} ${units[i]}`};
const escapeHtml=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const formatFactValue=value=>typeof value==="object"&&value!==null?JSON.stringify(value,null,2):String(value??"—");

function toast(message,error=false){const node=$("#toast");node.textContent=message;node.classList.toggle("error",error);node.classList.add("show");clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>node.classList.remove("show"),4200)}
function syncSettingInputs(key,value,source){settings[key]=value;$$(`[data-setting="${key}"]`).forEach(input=>{if(input!==source)input.checked=value})}
function bindSettings(){$$("[data-setting]").forEach(input=>{input.checked=settings[input.dataset.setting]??true;input.addEventListener("change",()=>syncSettingInputs(input.dataset.setting,input.checked,input))})}

async function api(path,options={}){
  const headers={...(options.headers||{})};
  if(options.method&&options.method!=="GET")headers["X-Caseflow-Token"]=csrfToken;
  if(options.body&&!(options.body instanceof FormData)){headers["Content-Type"]="application/json";options.body=JSON.stringify(options.body)}
  const response=await fetch(path,{...options,headers});
  const payload=await response.json();
  const errorMessage=typeof payload.error==="object"?payload.error?.message:payload.error;
  if(!response.ok||payload.ok===false)throw new Error(errorMessage||`HTTP ${response.status}`);
  return payload;
}

async function refresh(){
  try{
    const data=await api("/api/status");
    statusCache=data;csrfToken=data.csrfToken;
    $("#case-number").textContent=data.caseNumber;
    $("#metric-files").textContent=data.inbox.files;
    $("#metric-size").textContent=(data.inbox.bytes/1048576).toFixed(data.inbox.bytes?1:0);
    $("#metric-docs").textContent=data.lastRun?.statistics?.documents_added??"—";
    $("#metric-anomalies").textContent=data.anomalies?.summary?.open??"—";
    const connection=$("#connection-pill");
    connection.lastChild.textContent=data.activeJob?` ${data.activeJob.kind}`:" Локально";
    connection.classList.toggle("busy",Boolean(data.activeJob));
    renderRecent(data.recent);renderLastRun(data.lastRun);renderGoogle(data.google);
    if(data.archiveSupport&&!data.archiveSupport.rar)toast("RAR потребує 7-Zip. Запустіть інсталяційний майстер повторно.",true);
    if(data.ui?.panel_opacity)setOpacity(data.ui.panel_opacity,false);
    if(data.google.clientId&&!$("#google-client-id").value)$("#google-client-id").value=data.google.clientId;
  }catch(error){toast(error.message,true)}
}

function renderRecent(items){
  const body=$("#recent-body");
  if(!items.length){body.innerHTML='<tr><td colspan="4" class="muted">У 00_INBOX ще немає файлів.</td></tr>';return}
  body.innerHTML=items.map(item=>`<tr><td>${escapeHtml(item.name)}</td><td title="${escapeHtml(item.path)}">${escapeHtml(item.path)}</td><td>${new Date(item.modified).toLocaleString("uk-UA")}</td><td>${formatBytes(item.bytes)}</td></tr>`).join("");
}

function renderLastRun(run){
  if(!run)return;
  const s=run.statistics||{};
  $("#run-result").innerHTML=`<strong>Готово.</strong> Документів: ${s.documents_added??0}; файлів: ${s.files_added??0}; подій із підтвердженим часом: ${s.events_added??0}; cross_proceeding: ${s.cross_proceeding??0}.<br><span class="muted">Реєстр: ${escapeHtml(run.register||"створення вимкнено")}</span>`;
}

function renderGoogle(google){
  $("#drive-status").textContent=google.connected?"Підключено":google.configured?"Налаштовано, очікує входу":"Не налаштовано";
  $("#drive-sync").disabled=!google.connected;
  $("#drive-connect").textContent=google.connected?"Підключено":"Налаштувати й увійти";
}

async function loadContactContext(){
  try{
    contactContext=await api("/api/v1/contacts/context");
    renderContactRoleOptions();
  }catch(error){toast(error.message,true)}
}

async function loadContacts(){
  const query=$("#contact-query").value.trim();
  try{
    const result=await api(`/api/v1/contacts${query?`?q=${encodeURIComponent(query)}`:""}`);
    contactsCache=result.contacts||[];
    renderContactList();
    if(selectedContactId){
      const selected=contactsCache.find(contact=>contact.id===selectedContactId);
      if(selected)fillContactForm(selected);
    }else if(contactsCache.length){
      selectContact(contactsCache[0].id);
    }else{
      startNewContact();
    }
  }catch(error){
    $("#contact-list").innerHTML=`<div class="empty-state error-text">${escapeHtml(error.message)}</div>`;
  }
}

function renderContactList(){
  const type=$("#contact-type-filter").value;
  const contacts=contactsCache.filter(contact=>!type||contact.participant_type===type);
  $("#contact-count").textContent=`${contacts.length} контактів`;
  $("#contact-list").innerHTML=contacts.length?contacts.map(contact=>{
    const roles=(contact.roles||[]).slice(0,3).map(role=>escapeHtml(role.role)).join(" · ");
    const channels=[contact.phone,contact.email].filter(Boolean).map(escapeHtml).join(" · ");
    const kind=contact.participant_type==="organization"?"Організація":"Фізична особа";
    return `<button class="contact-row ${contact.id===selectedContactId?"active":""}" type="button" data-contact-id="${escapeHtml(contact.id)}">
      <span class="contact-avatar" aria-hidden="true">${contact.participant_type==="organization"?"ЮО":"ФО"}</span>
      <span class="contact-row-main"><b>${escapeHtml(contact.full_name)}</b><small>${escapeHtml(contact.short_name||kind)}</small><em>${channels||roles||"Без контактних каналів"}</em></span>
      <span class="contact-role-total">${(contact.roles||[]).length}</span>
    </button>`;
  }).join(""):'<div class="empty-state">Контактів немає.</div>';
}

function selectContact(contactId){
  const contact=contactsCache.find(item=>item.id===contactId);
  if(!contact)return;
  selectedContactId=contactId;
  fillContactForm(contact);
  renderContactList();
}

function startNewContact(){
  selectedContactId=null;
  $("#contact-form").reset();
  $("#contact-id").value="";
  $("#contact-active").checked=true;
  $("#contact-participant-type").value="person";
  $("#contact-detail-kind").textContent="Контакт";
  $("#contact-detail-title").textContent="Новий контакт";
  $("#contact-save-state").textContent="";
  $("#contact-roles-section").hidden=true;
  renderContactList();
  $("#contact-full-name").focus();
}

function fillContactForm(contact){
  const values={
    "#contact-id":contact.id,
    "#contact-full-name":contact.full_name,
    "#contact-participant-type":contact.participant_type,
    "#contact-short-name":contact.short_name,
    "#contact-email":contact.email,
    "#contact-phone":contact.phone,
    "#contact-additional-phone":contact.additional_phone,
    "#contact-date":contact.birth_or_registration_date,
    "#contact-tax-id":contact.tax_id,
    "#contact-edrpou":contact.edrpou,
    "#contact-address":contact.address,
    "#contact-representative":contact.representative_or_contact_person,
    "#contact-notes":contact.notes,
  };
  Object.entries(values).forEach(([selector,value])=>{$(selector).value=value??""});
  $("#contact-active").checked=Boolean(contact.active);
  $("#contact-detail-kind").textContent=contact.participant_type==="organization"?"Юридична особа":"Фізична особа";
  $("#contact-detail-title").textContent=contact.full_name;
  $("#contact-save-state").textContent="";
  $("#contact-roles-section").hidden=false;
  renderContactRoles(contact.roles||[]);
}

function contactPayload(){
  const optional=selector=>$(selector).value.trim()||null;
  return {
    full_name:$("#contact-full-name").value.trim(),
    participant_type:$("#contact-participant-type").value,
    active:$("#contact-active").checked,
    short_name:optional("#contact-short-name"),
    email:optional("#contact-email"),
    phone:optional("#contact-phone"),
    additional_phone:optional("#contact-additional-phone"),
    birth_or_registration_date:optional("#contact-date"),
    tax_id:optional("#contact-tax-id"),
    edrpou:optional("#contact-edrpou"),
    address:optional("#contact-address"),
    representative_or_contact_person:optional("#contact-representative"),
    notes:optional("#contact-notes"),
  };
}

async function saveContact(event){
  event.preventDefault();
  const payload=contactPayload();
  if(!payload.full_name){toast("Вкажіть ПІБ або назву",true);return}
  const button=$("#contact-save");button.disabled=true;
  $("#contact-save-state").textContent="Збереження…";
  try{
    const result=selectedContactId
      ?await api(`/api/v1/contacts/${encodeURIComponent(selectedContactId)}`,{method:"PATCH",body:payload})
      :await api("/api/v1/contacts",{method:"POST",body:payload});
    selectedContactId=result.contact.id;
    $("#contact-save-state").textContent="Збережено";
    toast("Контакт збережено");
    await loadContacts();
  }catch(error){
    $("#contact-save-state").textContent="Помилка";
    toast(error.message,true);
  }finally{button.disabled=false}
}

function renderContactRoleOptions(){
  $("#contact-role-case").innerHTML=(contactContext.cases||[]).map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.case_number||item.name||item.id)}</option>`).join("");
  $("#contact-role-name").innerHTML=(contactContext.roles||[]).map(role=>`<option value="${escapeHtml(role)}">${escapeHtml(role)}</option>`).join("");
  syncContactProceedings();
}

function syncContactProceedings(){
  const caseId=$("#contact-role-case").value;
  const options=(contactContext.proceedings||[]).filter(item=>!caseId||!item.caseIds?.length||item.caseIds.includes(caseId));
  $("#contact-role-proceeding").innerHTML='<option value="">Без окремого провадження</option>'+options.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.proceeding_number||item.name||item.id)}</option>`).join("");
}

function renderContactRoles(roles){
  const cases=new Map((contactContext.cases||[]).map(item=>[item.id,item.case_number||item.name||item.id]));
  const proceedings=new Map((contactContext.proceedings||[]).map(item=>[item.id,item.proceeding_number||item.name||item.id]));
  $("#contact-role-count").textContent=roles.length;
  $("#contact-role-list").innerHTML=roles.length?roles.map(role=>`<div class="contact-role-row"><b>${escapeHtml(role.role)}</b><span>${escapeHtml(cases.get(role.case_id)||role.case_id)}</span><small>${role.proceeding_id?escapeHtml(proceedings.get(role.proceeding_id)||role.proceeding_id):"Уся справа"}</small></div>`).join(""):'<div class="contact-role-empty">Ролей не призначено.</div>';
}

async function addContactRole(){
  if(!selectedContactId)return;
  const caseId=$("#contact-role-case").value,role=$("#contact-role-name").value;
  if(!caseId||!role){toast("Оберіть справу та роль",true);return}
  const button=$("#contact-role-add");button.disabled=true;
  try{
    const result=await api(`/api/v1/contacts/${encodeURIComponent(selectedContactId)}/roles`,{method:"POST",body:{case_id:caseId,proceeding_id:$("#contact-role-proceeding").value||null,role}});
    const index=contactsCache.findIndex(item=>item.id===selectedContactId);
    if(index>=0)contactsCache[index]=result.contact;
    fillContactForm(result.contact);renderContactList();toast("Роль додано");
  }catch(error){toast(error.message,true)}finally{button.disabled=false}
}

async function loadDocumentTree(){
  const container=$("#document-tree");
  container.innerHTML='<div class="empty-state">Завантаження дерева…</div>';
  try{
    documentTree=await api("/api/documents/tree");
    renderDocumentTree();
  }catch(error){
    container.innerHTML=`<div class="empty-state error-text">${escapeHtml(error.message)}</div>`;
  }
}

function renderDocumentTree(){
  if(!documentTree)return;
  const counts=documentTree.counts||{};
  $("#tree-count-all").textContent=counts.all||0;
  $("#tree-count-completed").textContent=counts.completed||0;
  $("#tree-count-in-progress").textContent=counts.in_progress||0;
  $("#tree-count-waiting").textContent=counts.waiting||0;
  $("#tree-count-needs-review").textContent=counts.needs_review||0;
  const query=$("#tree-query").value.trim().toLocaleLowerCase("uk-UA");
  let visibleDocuments=0;
  const groups=(documentTree.proceedings||[]).map(group=>{
    const documents=(group.documents||[]).filter(doc=>{
      const matchesStatus=treeStatus==="all"||doc.status===treeStatus;
      const haystack=JSON.stringify([group.number,group.rawStatus,doc.id,doc.name,doc.type,doc.flow,doc.summary,doc.nextAction,doc.files]).toLocaleLowerCase("uk-UA");
      return matchesStatus&&(!query||haystack.includes(query));
    });
    if(!documents.length)return"";
    visibleDocuments+=documents.length;
    const groupCounts=Object.entries(group.counts||{}).filter(([,value])=>value).map(([status,value])=>`<span class="tree-mini-status ${escapeHtml(status)}">${escapeHtml(treeStatusLabels[status]||status)}: ${value}</span>`).join("");
    const shouldOpen=Boolean(query)||treeStatus!=="all"||group.rawStatus==="В роботі";
    return `<details class="tree-proceeding" ${shouldOpen?"open":""}>
      <summary><span class="tree-chevron">›</span><span class="tree-folder-icon">▰</span><span class="tree-proceeding-title"><b>${escapeHtml(group.number)}</b><small>${escapeHtml(group.rawStatus||"Статус не вказано")} · ${documents.length} документів</small></span><span class="tree-group-counts">${groupCounts}</span></summary>
      <div class="tree-documents">${documents.map(renderTreeDocument).join("")}</div>
    </details>`;
  }).join("");
  $("#tree-meta").textContent=`Показано ${visibleDocuments} із ${counts.all||0} документів · Реєстр: ${documentTree.register||"не знайдено"}`;
  $("#document-tree").innerHTML=groups||'<div class="empty-state">За вибраним статусом або пошуком документів немає.</div>';
  $$('[data-document-status]').forEach(select=>{
    select.addEventListener("click",event=>event.stopPropagation());
    select.addEventListener("change",()=>updateDocumentStatus(select.dataset.documentStatus,select.value));
  });
}

function renderTreeDocument(doc){
  const groupedFiles=(doc.files||[]).reduce((groups,file)=>{const component=file.component||"Інше";(groups[component]??=[]).push(file);return groups},{});
  const files=Object.entries(groupedFiles).map(([component,items])=>`<section class="tree-file-branch"><h4><span>⌞</span>${escapeHtml(component)} <b>${items.length}</b></h4><ul class="tree-files">${items.map(file=>`<li><span class="tree-file-icon">▤</span><span><b>${escapeHtml(file.name)}</b><small>${formatBytes(Number(file.bytes)||0)}${file.integrity?` · ${escapeHtml(file.integrity)}`:""}</small><code title="${escapeHtml(file.path)}">${escapeHtml(file.path||"Шлях не вказано")}</code></span></li>`).join("")}</ul></section>`).join("");
  return `<details class="tree-document ${escapeHtml(doc.status)}">
    <summary><span class="status-dot"></span><span class="tree-document-main"><b>${escapeHtml(doc.id)} · ${escapeHtml(doc.name)}</b><small>${escapeHtml(doc.date||"Без дати")} · ${escapeHtml(doc.type||"Інше")} · ${escapeHtml(doc.flow||"Потік не вказано")}</small></span><span class="tree-file-count">${(doc.files||[]).length} файл(ів)</span><span class="tree-status-badge ${escapeHtml(doc.status)}">${escapeHtml(treeStatusLabels[doc.status]||doc.status)}</span></summary>
    <div class="tree-document-body">
      ${doc.summary?`<p>${escapeHtml(doc.summary)}</p>`:""}
      <label class="tree-status-editor"><span>Робочий статус${doc.statusManual?" · змінено вручну":""}</span><select data-document-status="${escapeHtml(doc.id)}">${treeStatusOptions(doc.status)}</select></label>
      ${doc.statusNote?`<p class="tree-status-note">Примітка статусу: ${escapeHtml(doc.statusNote)}</p>`:""}
      <div class="tree-document-facts"><span><b>Комплектність</b>${escapeHtml(doc.completeness||"Не вказано")}</span><span><b>Наступна дія</b>${escapeHtml(doc.nextAction||"Дій немає")}</span><span><b>Папка</b>${escapeHtml(doc.folder||"Не вказано")}</span></div>
      <div class="tree-file-branches">${files||'<p class="muted">Файли в Реєстрі не перелічені.</p>'}</div>
    </div>
  </details>`;
}

async function updateDocumentStatus(docId,status){
  try{
    await api("/api/documents/status",{method:"POST",body:{docId,status}});
    toast(`Статус ${docId} збережено`);
    await loadDocumentTree();
  }catch(error){toast(error.message,true);await loadDocumentTree()}
}

function setFiles(files){
  selectedFiles=[...files];
  const total=selectedFiles.reduce((sum,file)=>sum+file.size,0);
  const names=selectedFiles.slice(0,3).map(file=>file.webkitRelativePath||file.name);
  $("#selected-files").textContent=selectedFiles.length?`${selectedFiles.length} файлів · ${formatBytes(total)} · ${names.join(", ")}${selectedFiles.length>3?"…":""}`:"Файли ще не вибрано";
}

async function upload(){
  if(!selectedFiles.length){toast("Спочатку виберіть файли",true);return}
  const button=$("#upload-button");button.disabled=true;$("#upload-status").textContent="Зберігаю файли…";
  try{
    const form=new FormData();form.append("proceeding",$("#proceeding").value);form.append("flow",$("#flow").value);form.append("channel",$("#channel").value);form.append("options",JSON.stringify(settings));
    selectedFiles.forEach(file=>form.append("files",file,file.webkitRelativePath||file.name));
    const result=await api("/api/upload",{method:"POST",body:form});
    toast(`Збережено ${result.saved.length} файлів`);$("#upload-status").textContent=`Готово: ${result.destination}`;setFiles([]);$("#file-input").value="";$("#folder-input").value="";
    await Promise.all([refresh(),loadDocumentTree()]);
  }catch(error){toast(error.message,true);$("#upload-status").textContent="Не вдалося зберегти пакет."}finally{button.disabled=false}
}

async function processInbox(){
  const button=$("#process-button");button.disabled=true;button.textContent="Конвеєр працює…";
  $("#run-result").innerHTML='<span class="muted">Будую рекурсивну чергу, перевіряю ZIP, хронологію й створюю нову копію Реєстру…</span>';
  try{
    const result=await api("/api/process",{method:"POST",body:{settings}});
    const anomalySuffix=result.anomaly_error?`<br><span class="error-text">Контроль нестиковок: ${escapeHtml(result.anomaly_error)}</span>`:result.anomalies?`<br><span class="muted">Відкритих сигналів: ${result.anomalies.summary?.open??0}.</span>`:"";
    $("#run-result").innerHTML=`<strong>Готово.</strong> Документів: ${result.documents_added}; файлів: ${result.files_added}; подій: ${result.events_added}; дублів пропущено: ${result.duplicates_skipped}; cross_proceeding: ${result.cross_proceeding}.<br><span class="muted">Реєстр: ${escapeHtml(result.register||"створення вимкнено")}</span>${anomalySuffix}`;
    if(result.anomalies)setAnomalyReport({available:true,...result.anomalies});
    toast("Опрацювання завершено");await Promise.all([refresh(),loadDocumentTree()]);
  }catch(error){toast(error.message,true);$("#run-result").innerHTML=`<span class="error-text">${escapeHtml(error.message)}</span>`}finally{button.disabled=false;button.textContent="Запустити конвеєр"}
}

function setAnomalyReport(report){
  anomalyReport=report;findingLimit=100;
  const categories=[...new Set((report.findings||[]).map(item=>item.category).filter(Boolean))].sort();
  const select=$("#filter-category"),selected=select.value;
  select.innerHTML='<option value="">Усі</option>'+categories.map(value=>`<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  if(categories.includes(selected))select.value=selected;
  renderAnomalies();
}

function renderAnomalies(){
  const report=anomalyReport;
  if(!report?.available){$("#anomaly-list").innerHTML='<div class="empty-state">Перевірка ще не запускалась.</div>';return}
  const summary=report.summary||{};
  $("#risk-score").textContent=summary.risk_score??0;
  ["critical","high","medium","low"].forEach(level=>{$(`#count-${level}`).textContent=summary[level]??0});
  $("#metric-anomalies").textContent=summary.open??0;
  $("#anomaly-meta").textContent=`Звіт: ${new Date(report.generated_at).toLocaleString("uk-UA")} · Реєстр: ${report.register} · відкрито ${summary.open??0} із ${summary.total??0}`;
  const severity=$("#filter-severity").value,status=$("#filter-status").value,category=$("#filter-category").value,query=$("#filter-query").value.trim().toLocaleLowerCase("uk-UA");
  const filtered=(report.findings||[]).filter(item=>{
    const haystack=JSON.stringify([item.title,item.discrepancy,item.doc_ids,item.proceedings,item.rule_id,item.facts]).toLocaleLowerCase("uk-UA");
    return(!severity||item.severity===severity)&&(!status||item.status===status)&&(!category||item.category===category)&&(!query||haystack.includes(query));
  });
  const visible=filtered.slice(0,findingLimit);
  const more=filtered.length>visible.length?`<button class="secondary anomaly-more" data-show-more="true">Показати ще ${Math.min(100,filtered.length-visible.length)} · залишилось ${filtered.length-visible.length}</button>`:"";
  $("#anomaly-list").innerHTML=filtered.length?visible.map(renderFinding).join("")+more:'<div class="empty-state">За вибраними фільтрами карток немає.</div>';
}

function renderFinding(item){
  const facts=(item.facts||[]).map((entry,index)=>`<tr><td><span class="fact-side">${String.fromCharCode(65+index)}</span>${escapeHtml(entry.source_type)}</td><td><b>${escapeHtml(entry.field)}</b><pre>${escapeHtml(formatFactValue(entry.value))}</pre></td><td title="${escapeHtml(entry.source_path)}">${escapeHtml(entry.source_path)}</td><td>${entry.observed_at?escapeHtml(new Date(entry.observed_at).toLocaleString("uk-UA")):"—"}</td></tr>`).join("");
  const chips=[...(item.doc_ids||[]),...Object.values(item.proceedings||{}).flat()].filter(Boolean).map(value=>`<span>${escapeHtml(value)}</span>`).join("");
  const explanations=(item.possible_benign_explanations||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join("");
  return `<article class="finding ${escapeHtml(item.severity)}" data-fingerprint="${escapeHtml(item.fingerprint)}">
    <header><div><span class="severity-badge ${escapeHtml(item.severity)}">${escapeHtml(severityLabels[item.severity]||item.severity)}</span><span class="confidence">впевненість: ${escapeHtml(confidenceLabels[item.confidence]||item.confidence)}</span><span class="rule-id">${escapeHtml(item.rule_id)}</span></div><span class="review-status ${escapeHtml(item.status)}">${escapeHtml(statusLabels[item.status]||item.status)}</span></header>
    <h3>${escapeHtml(item.title)}</h3><p class="discrepancy">${escapeHtml(item.discrepancy)}</p><div class="finding-chips">${chips}</div>
    <details><summary>Показати факти та джерела</summary><div class="fact-table-wrap"><table class="fact-table"><thead><tr><th>Сторона</th><th>Поле / значення</th><th>Джерело</th><th>Зафіксовано</th></tr></thead><tbody>${facts}</tbody></table></div>
      <div class="analysis-grid"><div><b>Чому позначено</b><p>${escapeHtml(item.why_flagged)}</p></div><div><b>Що перевірити</b><p>${escapeHtml(item.next_check)}</p></div><div><b>Можливі нейтральні пояснення</b><ul>${explanations}</ul></div></div>
    </details>
    ${item.status_note?`<p class="status-note">Нотатка: ${escapeHtml(item.status_note)}</p>`:""}
    <footer><span>${escapeHtml(item.anomaly_id)} · ${escapeHtml(item.fingerprint)}</span><div class="review-actions"><button class="ghost" data-review-status="open">Відкрити</button><button class="ghost" data-review-status="acknowledged">Взяти до уваги</button><button class="ghost" data-review-status="resolved">Пояснено</button><button class="ghost danger" data-review-status="false_positive">Хибний сигнал</button></div></footer>
  </article>`;
}

async function loadAnomalies(){try{setAnomalyReport(await api("/api/anomalies/latest"))}catch(error){toast(error.message,true)}}
async function runAnomalies(){
  const button=$("#anomaly-button");button.disabled=true;button.textContent="Перевіряю…";
  try{const report=await api("/api/anomalies/run",{method:"POST",body:{}});setAnomalyReport(report);toast(`Знайдено відкритих сигналів: ${report.summary.open}`);await refresh()}catch(error){toast(error.message,true)}finally{button.disabled=false;button.textContent="Запустити перевірку"}
}

async function updateAnomalyStatus(fingerprint,status){
  const current=anomalyReport?.findings?.find(item=>item.fingerprint===fingerprint);
  const note=window.prompt("Коротка нотатка ручної перевірки (можна залишити порожньою):",current?.status_note||"");
  if(note===null)return;
  try{
    const result=await api("/api/anomalies/status",{method:"POST",body:{fingerprint,status,note}});
    if(current){current.status=status;current.status_note=note}anomalyReport.summary=result.summary;renderAnomalies();toast("Статус картки збережено");
  }catch(error){toast(error.message,true)}
}

function setOpacity(value,save=true){value=Math.max(45,Math.min(98,Number(value)));document.documentElement.style.setProperty("--widget-opacity",value/100);$("#opacity-range").value=value;$("#opacity-output").textContent=`${value}%`;if(save&&csrfToken){clearTimeout(window.opacityTimer);window.opacityTimer=setTimeout(()=>api("/api/settings",{method:"POST",body:{panelOpacity:value}}).catch(()=>{}),350)}}
async function saveGoogle(){try{await api("/api/google/config",{method:"POST",body:{clientId:$("#google-client-id").value.trim(),clientSecret:$("#google-client-secret").value.trim()}});toast("OAuth-параметри збережено");await refresh()}catch(error){toast(error.message,true)}}
async function connectGoogle(){if(statusCache?.google?.connected){toast("Google Drive вже підключено");return}if(!$("#google-client-id").value.trim()){$("#oauth-details").open=true;toast("Вкажіть OAuth Client ID типу Desktop app",true);return}try{await saveGoogle();const result=await api("/api/google/login",{method:"POST",body:{}});window.open(result.url,"caseflow-google-oauth","width=720,height=760");const timer=setInterval(async()=>{await refresh();if(statusCache?.google?.connected){clearInterval(timer);toast("Google Drive підключено")}},1800);setTimeout(()=>clearInterval(timer),180000)}catch(error){toast(error.message,true)}}
async function syncDrive(){const folders=$$("[data-drive]:checked").map(input=>input.dataset.drive);const button=$("#drive-sync");button.disabled=true;button.textContent="Синхронізація…";try{const result=await api("/api/google/sync",{method:"POST",body:{folders}});toast(`Drive: завантажено ${result.uploaded}, без змін ${result.skipped}`)}catch(error){toast(error.message,true)}finally{button.textContent="Синхронізувати вибране";button.disabled=!statusCache?.google?.connected}}
async function disconnectGoogle(){try{await api("/api/google/disconnect",{method:"POST",body:{}});toast("Google Drive від’єднано");await refresh()}catch(error){toast(error.message,true)}}

document.addEventListener("DOMContentLoaded",()=>{
  bindSettings();
  const drop=$("#drop-zone");
  $("#add-document-button").addEventListener("click",()=>{
    drop.scrollIntoView({behavior:"smooth",block:"center"});
    $("#file-input").click();
  });
  $("#choose-files").addEventListener("click",event=>{event.stopPropagation();$("#file-input").click()});
  $("#choose-folder").addEventListener("click",event=>{event.stopPropagation();$("#folder-input").click()});
  drop.addEventListener("click",()=>$("#file-input").click());
  drop.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();$("#file-input").click()}});
  $("#file-input").addEventListener("change",event=>setFiles(event.target.files));
  $("#folder-input").addEventListener("change",event=>setFiles(event.target.files));
  ["dragenter","dragover"].forEach(type=>drop.addEventListener(type,event=>{event.preventDefault();drop.classList.add("dragover")}));
  ["dragleave","drop"].forEach(type=>drop.addEventListener(type,event=>{event.preventDefault();drop.classList.remove("dragover")}));
  drop.addEventListener("drop",event=>setFiles(event.dataTransfer.files));
  $("#upload-button").addEventListener("click",upload);$("#process-button").addEventListener("click",processInbox);$("#anomaly-button").addEventListener("click",runAnomalies);$("#refresh-button").addEventListener("click",async()=>{await refresh();await loadAnomalies()});
  $("#tree-refresh").addEventListener("click",loadDocumentTree);
  $("#tree-query").addEventListener("input",renderDocumentTree);
  $("#contact-new").addEventListener("click",startNewContact);
  $("#contact-form").addEventListener("submit",saveContact);
  $("#contact-list").addEventListener("click",event=>{const row=event.target.closest("[data-contact-id]");if(row)selectContact(row.dataset.contactId)});
  $("#contact-type-filter").addEventListener("change",renderContactList);
  $("#contact-query").addEventListener("input",()=>{clearTimeout(window.contactSearchTimer);window.contactSearchTimer=setTimeout(loadContacts,180)});
  $("#contact-role-case").addEventListener("change",syncContactProceedings);
  $("#contact-role-add").addEventListener("click",addContactRole);
  $$("[data-tree-status]").forEach(button=>button.addEventListener("click",()=>{treeStatus=button.dataset.treeStatus;$$('[data-tree-status]').forEach(item=>item.classList.toggle("active",item===button));renderDocumentTree()}));
  ["#filter-severity","#filter-status","#filter-category"].forEach(selector=>$(selector).addEventListener("change",()=>{findingLimit=100;renderAnomalies()}));$("#filter-query").addEventListener("input",()=>{findingLimit=100;renderAnomalies()});
  $("#anomaly-list").addEventListener("click",event=>{const more=event.target.closest("[data-show-more]");if(more){findingLimit+=100;renderAnomalies();return}const button=event.target.closest("[data-review-status]");if(!button)return;const card=button.closest("[data-fingerprint]");updateAnomalyStatus(card.dataset.fingerprint,button.dataset.reviewStatus)});
  $("#opacity-range").addEventListener("input",event=>setOpacity(event.target.value));$("#collapse-widget").addEventListener("click",()=>$("#widget").classList.toggle("collapsed"));$("#save-google").addEventListener("click",saveGoogle);$("#drive-connect").addEventListener("click",connectGoogle);$("#drive-sync").addEventListener("click",syncDrive);$("#disconnect-google").addEventListener("click",disconnectGoogle);
  $("#flow").addEventListener("change",event=>{$("#channel").value=event.target.value==="01_ВІД_СУДУ"?"ЕСУД_СУД":"ЕСУД_МОЇ"});
  Promise.all([refresh(),loadAnomalies(),loadDocumentTree(),loadContactContext().then(loadContacts)]);
});
