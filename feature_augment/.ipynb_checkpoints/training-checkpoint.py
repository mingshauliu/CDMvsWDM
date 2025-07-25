"""
CNN for CDM/WDM Cosmic Web Classification
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
import os
import numpy as np
import random
import matplotlib.pyplot as plt
import time
from utils import set_seed, load_dataset, plot_feature_maps, plot_training_progress, evaluate_model, radial_power_spectrum
from transform import TensorAugment, SimpleResize
from models import SimpleCNN, BigCNN

def main():
    """Main training function"""
    # Set random seed for reproducibility
    set_seed(23)
    
    # Configuration
    config = {
        'img_size': 256,
        'dropout': 0.0,
        'batch_size': 64,
        'lr': 1e-4,
        'weight_decay': 1e-3,
        'epochs': 80,
        'patience': 20,
        'k_samples': 10000,  # Number of samples to use
        'model_type': 'simple',  # 'simple' or 'big'
        'blur_kernel': 0,
    }
    
    cdm_file='/n/netscratch/iaifi_lab/Lab/msliu/CMD/data/IllustrisTNG/Maps_Mtot_IllustrisTNG_LH_z=0.00.npy'
    wdm_file='/n/netscratch/iaifi_lab/Lab/ccuestalazaro/DREAMS/Images/WDM/boxes/Maps_Mtot_IllustrisTNG_WDM_z=0.00.npy'
    
    print("=== CNN Training ===")
    print(f"Configuration: {config}")
    
    # Load WDM mass data (if needed)
    try:
        WDM_mass = []
        with open('WDM_TNG_MW_SB4.txt', 'r') as f:
            for i, line in enumerate(f.readlines()[1:]):
                WDM_mass.append([i, float(line.strip().split(' ')[0])])
        WDM_mass = np.array(WDM_mass)
        print(f"Loaded WDM mass data: {len(WDM_mass)} entries")
    except FileNotFoundError:
        print("Warning: WDM_TNG_MW_SB4.txt not found, using random indices")
        WDM_mass = None
    # Load files
    # cdm = np.load(cdm_file)
    # wdm = np.load(wdm_file)
    # N = 500
    # assert cdm.shape[0] >= N and wdm.shape[0] >= N

    # print("Computing mean P(k) for CDM...")
    # cdm_pks = [radial_power_spectrum(torch.from_numpy(cdm[i]).float()) for i in range(N)]
    # mu_cdm = np.mean(cdm_pks, axis=0)

    # print("Computing mean P(k) for WDM...")
    # wdm_pks = [radial_power_spectrum(torch.from_numpy(wdm[i]).float()) for i in range(N)]
    # mu_wdm = np.mean(wdm_pks, axis=0)

    # np.save("mu_pk_cdm.npy", mu_cdm.astype(np.float32))
    # np.save("mu_pk_wdm.npy", mu_wdm.astype(np.float32))
    # print("Done.")
    
    # Sample indices
    all_indices = random.sample(range(15000), config['k_samples'])
    random.shuffle(all_indices)
    
    # Split data
    train_ratio, val_ratio = 0.6, 0.2
    total_samples = len(all_indices)
    train_end = int(train_ratio * total_samples)
    val_end = int((train_ratio + val_ratio) * total_samples)
    
    train_indices = all_indices[:train_end]
    val_indices = all_indices[train_end:val_end]
    test_indices = all_indices[val_end:]
    
    print(f"\nDataset split:")
    print(f"Total: {total_samples}, Train: {len(train_indices)}, Val: {len(val_indices)}, Test: {len(test_indices)}")
    
    # Create transforms (keeping log scale and augmentation intact)
    train_transform = TensorAugment(
        size=(config['img_size'], config['img_size']),
        p_flip=0.0,
        p_rot=0.0,
        noise_std=0, # Stop noise temporarily
        blur_kernel=config['blur_kernel'],
        apply_log=True  # Keep log scale
    )
    
    val_test_transform = SimpleResize(
        size=(config['img_size'], config['img_size']),
        apply_log=True  # Keep log scale
    )
    
    # Create datasets
    print("\nLoading datasets...")
    train_dataset = load_dataset(train_indices, transform=train_transform, cdm_file=cdm_file, wdm_file=wdm_file)
    val_dataset = load_dataset(val_indices, transform=val_test_transform, cdm_file=cdm_file, wdm_file=wdm_file)
    test_dataset = load_dataset(test_indices, transform=val_test_transform, cdm_file=cdm_file, wdm_file=wdm_file)

    
    # Create data loaders
    train_loader = DataLoader(train_dataset, batch_size=config['batch_size'], shuffle=True, 
                             num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=config['batch_size'], shuffle=False, 
                           num_workers=4, pin_memory=True)
    test_loader = DataLoader(test_dataset, batch_size=config['batch_size'], shuffle=False, 
                            num_workers=4, pin_memory=True)
    
    print(f"Data loaders created: Train={len(train_loader)}, Val={len(val_loader)}, Test={len(test_loader)} batches")
    
    # Model setup
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    if config['model_type'] == 'simple':
        model = SimpleCNN(
            in_channels=1,
            num_classes=1,
            dropout=config['dropout']
        ).to(device)
        print("Using SimpleCNN")
    else:
        model = BigCNN(
            in_channels=1,
            num_classes=1,
            dropout=config['dropout']
        ).to(device)
        print("Using BigCNN")
    
    # Print model info
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Model parameters: {total_params:,} total, {trainable_params:,} trainable")
    
    # Loss and optimizer
    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.AdamW(model.parameters(), lr=config['lr'], weight_decay=config['weight_decay'])
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        patience=5,
        factor=0.5
    )
    
    # Training tracking
    train_loss_hist, train_acc_hist, val_acc_hist = [], [], []
    best_val_acc = 0.0
    patience_counter = 0
    
    start_epoch = 0
    if os.path.exists(f"best_cnn_model_blur_{config['blur_kernel']}.pt"):
        print("Resuming from checkpoint...")
        checkpoint = torch.load(f"best_cnn_model_blur_{config['blur_kernel']}.pt", map_location=device, weights_only=True)
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        best_val_acc = checkpoint.get('val_acc', 0.0)
        start_epoch = checkpoint.get('epoch', 0) + 1
        print(f"Resumed from epoch {start_epoch} with val_acc={best_val_acc:.4f}")

    
    print(f"\nStarting training for {config['epochs']} epochs...")

    # Training loop
    for epoch in range(start_epoch, config['epochs']):
        # Training phase
        model.train()
        train_loss, train_correct = 0.0, 0
        start_time = time.time()
        num_batches = len(train_loader)
        
        for batch_idx, (images, labels, pks) in enumerate(train_loader):
            batch_start = time.time()
            images = images.to(device)
            labels = labels.to(device).unsqueeze(1)
            pks = pks.to(device)
            
            optimizer.zero_grad()
            outputs = model(images, pks)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item() * labels.size(0)
            preds = (torch.sigmoid(outputs) > 0.5).float()
            train_correct += (preds == labels).sum().item()
            
            batch_time = time.time() - batch_start
            if batch_idx == 0:
                print(f"  First batch time: {batch_time:.3f}s")
        
        total_time = time.time() - start_time
        iters_per_sec = len(train_loader.dataset) / total_time
        print(f"  Iterations/sec: {iters_per_sec:.2f}, Total epoch time: {total_time:.2f}s")
        avg_train_loss = train_loss / len(train_loader.dataset)
        train_acc = train_correct / len(train_loader.dataset)
        
        # Validation phase
        avg_val_loss, val_acc = evaluate_model(model, val_loader, criterion, device)
        scheduler.step(avg_val_loss)
        
        # Record history
        train_loss_hist.append(avg_train_loss)
        train_acc_hist.append(train_acc)
        val_acc_hist.append(val_acc)
        
        print(f"Epoch {epoch+1:3d}: Train Loss={avg_train_loss:.4f}, Train Acc={train_acc:.4f}, "
              f"Val Loss={avg_val_loss:.4f}, Val Acc={val_acc:.4f}")
        
        # Early stopping and model saving
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience_counter = 0
            torch.save({
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'val_loss': avg_val_loss,
                'val_acc': val_acc,
                'config': config
            }, f"best_cnn_model_blur_{config['blur_kernel']}.pt")
            print(f"  -> New best model saved (Val Acc: {val_acc:.4f})")
        else:
            patience_counter += 1
            if patience_counter >= config['patience']:
                print(f"Early stopping triggered after {epoch+1} epochs")
                break
    
    # Load best model for final evaluation
    print("\nLoading best model for final evaluation...")
    checkpoint = torch.load(f"best_cnn_model_blur_{config['blur_kernel']}.pt", map_location=device, weights_only=True)
    model.load_state_dict(checkpoint['model_state_dict'])
    
    # Final evaluation
    test_loss, test_acc = evaluate_model(model, test_loader, criterion, device)
    print(f"\nFinal Results:")
    print(f"Best Val Acc: {best_val_acc:.4f}")
    print(f"Test Acc: {test_acc:.4f}")
    
    # Plot training progress
    plot_training_progress(train_loss_hist, train_acc_hist, val_acc_hist, f'cnn_training_progress_blur_{config['blur_kernel']}.png')
    
    # Generate feature map visualization
    if len(test_loader) > 0:
        plot_feature_maps(model, test_loader, device, f'cnn_feature_maps_blur_{config['blur_kernel']}.png')
    
    print("\nTraining completed!")


if __name__ == "__main__":
    main()