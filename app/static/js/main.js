document.addEventListener('DOMContentLoaded', function() {
    // LED effect for buttons
    const primaryButtons = document.querySelectorAll('.btn-primary');
    
    primaryButtons.forEach(button => {
        // Create LED glow effect
        const glow = document.createElement('div');
        glow.classList.add('led-glow');
        button.appendChild(glow);
        
        // Add hover animation
        button.addEventListener('mouseover', function() {
            glow.style.opacity = '0.8';
        });
        
        button.addEventListener('mouseout', function() {
            glow.style.opacity = '0.4';
        });
    });
    
    // Entitlements extraction functionality
    const extractEntitlementsBtn = document.getElementById('extract-entitlements-btn');
    const entitlementsContainer = document.getElementById('entitlements-container');
    const applyEntitlementsBtn = document.getElementById('apply-entitlements-btn');
    const entitlementsTextarea = document.getElementById('entitlements');
    const entitlementsContent = document.querySelector('.entitlements-content');
    const loadingSpinner = document.querySelector('.loading-spinner');
    
    if (extractEntitlementsBtn) {
        extractEntitlementsBtn.addEventListener('click', function() {
            const ipaInput = document.getElementById('ipa_file');
            const provisionInput = document.getElementById('provision_file');
            
            if (!ipaInput.files[0] || !provisionInput.files[0]) {
                alert('Please upload both an IPA file and a provisioning profile to extract entitlements.');
                return;
            }
            
            // Show the entitlements container and loading spinner
            entitlementsContainer.style.display = 'block';
            loadingSpinner.style.display = 'block';
            entitlementsContent.style.display = 'none';
            applyEntitlementsBtn.style.display = 'none';
            
            // Create FormData object
            const formData = new FormData();
            formData.append('ipa_file', ipaInput.files[0]);
            formData.append('provision_file', provisionInput.files[0]);
            
            // Send AJAX request to extract entitlements
            fetch('/extract_entitlements', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                // Hide loading spinner
                loadingSpinner.style.display = 'none';
                
                if (data.error) {
                    entitlementsContent.innerHTML = `<div class="error-message">${data.error}</div>`;
                    entitlementsContent.style.display = 'block';
                    return;
                }
                
                // Create entitlements table
                let tableHtml = '<table class="entitlements-table">';
                tableHtml += '<thead><tr><th>Select</th><th>Key</th><th>Value</th><th>Source</th></tr></thead>';
                tableHtml += '<tbody>';
                
                // Add entitlements from IPA
                if (data.ipa_entitlements) {
                    Object.entries(data.ipa_entitlements).forEach(([key, value]) => {
                        tableHtml += `
                            <tr>
                                <td><input type="checkbox" class="entitlement-checkbox" data-key="${key}" data-value='${JSON.stringify(value)}' checked></td>
                                <td>${key}</td>
                                <td><pre>${JSON.stringify(value, null, 2)}</pre></td>
                                <td><span class="badge badge-ipa">IPA</span></td>
                            </tr>
                        `;
                    });
                }
                
                // Add entitlements from provisioning profile
                if (data.profile_entitlements) {
                    Object.entries(data.profile_entitlements).forEach(([key, value]) => {
                        // Check if this key already exists in IPA entitlements
                        const existsInIpa = data.ipa_entitlements && data.ipa_entitlements.hasOwnProperty(key);
                        
                        if (!existsInIpa) {
                            tableHtml += `
                                <tr>
                                    <td><input type="checkbox" class="entitlement-checkbox" data-key="${key}" data-value='${JSON.stringify(value)}' checked></td>
                                    <td>${key}</td>
                                    <td><pre>${JSON.stringify(value, null, 2)}</pre></td>
                                    <td><span class="badge badge-profile">Profile</span></td>
                                </tr>
                            `;
                        }
                    });
                }
                
                tableHtml += '</tbody></table>';
                
                // Display entitlements table
                entitlementsContent.innerHTML = tableHtml;
                entitlementsContent.style.display = 'block';
                applyEntitlementsBtn.style.display = 'block';
            })
            .catch(error => {
                loadingSpinner.style.display = 'none';
                entitlementsContent.innerHTML = `<div class="error-message">Error extracting entitlements: ${error.message}</div>`;
                entitlementsContent.style.display = 'block';
            });
        });
    }
    
    // Apply selected entitlements
    if (applyEntitlementsBtn) {
        applyEntitlementsBtn.addEventListener('click', function() {
            const selectedEntitlements = {};
            const checkboxes = document.querySelectorAll('.entitlement-checkbox:checked');
            
            checkboxes.forEach(checkbox => {
                const key = checkbox.dataset.key;
                const value = JSON.parse(checkbox.dataset.value);
                selectedEntitlements[key] = value;
            });
            
            // Generate XML plist from selected entitlements
            const xmlContent = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
${Object.entries(selectedEntitlements).map(([key, value]) => {
    return `    <key>${key}</key>
    ${formatPlistValue(value)}`;
}).join('\n')}
</dict>
</plist>`;
            
            // Set the entitlements textarea value
            entitlementsTextarea.value = xmlContent;
            
            // Hide the entitlements container
            entitlementsContainer.style.display = 'none';
            
            // Show success message
            alert('Entitlements have been applied to the form.');
        });
    }
    
    // Helper function to format plist values
    function formatPlistValue(value) {
        if (typeof value === 'boolean') {
            return value ? '<true/>' : '<false/>';
        } else if (typeof value === 'string') {
            return `<string>${value}</string>`;
        } else if (typeof value === 'number') {
            if (Number.isInteger(value)) {
                return `<integer>${value}</integer>`;
            } else {
                return `<real>${value}</real>`;
            }
        } else if (Array.isArray(value)) {
            return `<array>
        ${value.map(item => `    ${formatPlistValue(item)}`).join('\n')}
    </array>`;
        } else if (typeof value === 'object' && value !== null) {
            return `<dict>
        ${Object.entries(value).map(([k, v]) => `    <key>${k}</key>
        ${formatPlistValue(v)}`).join('\n')}
    </dict>`;
        } else {
            return '<string></string>'; // Default for null or undefined
        }
    }
    
    // Flash message handling
    const flashMessages = document.querySelectorAll('.flash-message');
    const closeButtons = document.querySelectorAll('.flash-message .close-btn');
    
    // Auto-hide flash messages after 5 seconds
    flashMessages.forEach(message => {
        setTimeout(() => {
            message.style.opacity = '0';
            setTimeout(() => {
                message.style.display = 'none';
            }, 300);
        }, 5000);
    });
    
    // Close button functionality
    closeButtons.forEach(button => {
        button.addEventListener('click', function() {
            const message = this.parentElement;
            message.style.opacity = '0';
            setTimeout(() => {
                message.style.display = 'none';
            }, 300);
        });
    });
    
    // File input styling
    const fileInputs = document.querySelectorAll('.file-input');
    
    fileInputs.forEach(input => {
        input.addEventListener('change', function() {
            const fileName = this.files[0]?.name || 'No file chosen';
            const fileNameDisplay = this.parentElement.nextElementSibling;
            
            if (this.files.length > 0) {
                fileNameDisplay.textContent = fileName;
                fileNameDisplay.classList.add('has-file');
            } else {
                fileNameDisplay.textContent = 'No file chosen';
                fileNameDisplay.classList.remove('has-file');
            }
        });
    });
    
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            const targetElement = document.querySelector(targetId);
            
            if (targetElement) {
                window.scrollTo({
                    top: targetElement.offsetTop - 100,
                    behavior: 'smooth'
                });
            }
        });
    });
    
    // Add neon border effect to form
    const signingForm = document.querySelector('.signing-form');
    
    if (signingForm) {
        // Create neon border elements
        const borders = ['top', 'right', 'bottom', 'left'];
        
        borders.forEach(position => {
            const border = document.createElement('div');
            border.classList.add('neon-border', `border-${position}`);
            signingForm.appendChild(border);
        });
        
        // Animate neon borders
        let hue = 240; // Start with blue
        
        setInterval(() => {
            hue = (hue + 1) % 360;
            const color = `hsl(${hue}, 100%, 70%)`;
            
            document.querySelectorAll('.neon-border').forEach(border => {
                border.style.boxShadow = `0 0 10px ${color}`;
                border.style.backgroundColor = color;
            });
        }, 100);
    }
    
    // Add particle background effect to hero section
    const heroSection = document.querySelector('.hero');
    
    if (heroSection) {
        // Create canvas for particles
        const canvas = document.createElement('canvas');
        canvas.classList.add('particles-canvas');
        canvas.style.position = 'absolute';
        canvas.style.top = '0';
        canvas.style.left = '0';
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.zIndex = '1';
        canvas.style.pointerEvents = 'none';
        
        heroSection.insertBefore(canvas, heroSection.firstChild);
        
        // Set canvas size
        canvas.width = heroSection.offsetWidth;
        canvas.height = heroSection.offsetHeight;
        
        // Initialize particles
        const ctx = canvas.getContext('2d');
        const particles = [];
        
        for (let i = 0; i < 50; i++) {
            particles.push({
                x: Math.random() * canvas.width,
                y: Math.random() * canvas.height,
                radius: Math.random() * 2 + 1,
                color: `rgba(${Math.floor(Math.random() * 100 + 155)}, ${Math.floor(Math.random() * 100 + 155)}, 255, ${Math.random() * 0.5 + 0.25})`,
                speedX: Math.random() * 2 - 1,
                speedY: Math.random() * 2 - 1
            });
        }
        
        // Animate particles
        function animateParticles() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            particles.forEach(particle => {
                // Move particle
                particle.x += particle.speedX;
                particle.y += particle.speedY;
                
                // Bounce off edges
                if (particle.x < 0 || particle.x > canvas.width) {
                    particle.speedX *= -1;
                }
                
                if (particle.y < 0 || particle.y > canvas.height) {
                    particle.speedY *= -1;
                }
                
                // Draw particle
                ctx.beginPath();
                ctx.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
                ctx.fillStyle = particle.color;
                ctx.fill();
            });
            
            requestAnimationFrame(animateParticles);
        }
        
        animateParticles();
        
        // Resize canvas when window resizes
        window.addEventListener('resize', function() {
            canvas.width = heroSection.offsetWidth;
            canvas.height = heroSection.offsetHeight;
        });
    }
});